"""Sentinel Hub NDVI engine using the Statistics API."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any, Final, cast

import httpx
from django.conf import settings
from django.core.cache import caches

from ndvi.metrics import (
    ndvi_cache_hit_total,
    ndvi_upstream_latency_seconds,
    ndvi_upstream_requests_total,
)

from .base import BBox, NDVIEngine, NdviPoint

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT: Final[float] = float(
    getattr(settings, "NDVI_REQUEST_TIMEOUT_SECONDS", 20)
)
DEFAULT_MAX_CLOUD: Final[int] = int(
    getattr(settings, "NDVI_DEFAULT_MAX_CLOUD", 30)
)
DEFAULT_STEP_DAYS: Final[int] = int(
    getattr(settings, "NDVI_DEFAULT_STEP_DAYS", 7)
)
DEFAULT_LOOKBACK_DAYS: Final[int] = int(
    getattr(settings, "NDVI_DEFAULT_LOOKBACK_DAYS", 14)
)

NDVI_EVALSCRIPT: Final[str] = """
//VERSION=3
function setup() {
  return {
    input: [{bands: ["B08", "B04", "SCL"]}],
    output: [
      { id: "ndvi", bands: 1, sampleType: "FLOAT32", statistics: true },
      { id: "dataMask", bands: 1 }
    ]
  };
}

const MASKED_SCL = [3, 8, 9, 10, 11]; // cloud/shadow/high-probability

function isClear(sceneClass) {
  return MASKED_SCL.indexOf(sceneClass) === -1;
}

function evaluatePixel(sample) {
  const ndvi = (sample.B08 - sample.B04) / (sample.B08 + sample.B04);
  const mask = isFinite(ndvi) && isClear(sample.SCL) ? 1 : 0;
  return { ndvi: [ndvi], dataMask: [mask] };
}
"""


class SentinelHubEngine(NDVIEngine):
    """Fetch NDVI metrics from Sentinel Hub APIs."""

    engine_name: Final[str] = "sentinelhub"

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        cache_alias: str = "default",
        timeout_seconds: float | None = None,
        base_url: str | None = None,
    ) -> None:
        self.client_id = client_id or os.getenv("SENTINELHUB_CLIENT_ID")
        self.client_secret = client_secret or os.getenv(
            "SENTINELHUB_CLIENT_SECRET"
        )
        if not self.client_id or not self.client_secret:
            raise ValueError("Sentinel Hub client credentials are required")

        self.base_url = base_url or os.getenv(
            "SENTINELHUB_BASE_URL", "https://services.sentinel-hub.com"
        )
        self.token_url = f"{self.base_url}/oauth/token"
        self.statistics_url = f"{self.base_url}/api/v1/statistics"
        self.cache = caches[cache_alias]
        self.timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT
        self._http = httpx.Client(timeout=self.timeout_seconds)

    def get_timeseries(
        self,
        *,
        bbox: BBox,
        start: date,
        end: date,
        step_days: int = DEFAULT_STEP_DAYS,
        max_cloud: int = DEFAULT_MAX_CLOUD,
    ) -> list[NdviPoint]:
        payload = self._build_statistics_payload(
            bbox=bbox,
            start=start,
            end=end,
            step_days=step_days,
            max_cloud=max_cloud,
        )
        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        response = self._request_with_retry(
            "POST",
            self.statistics_url,
            json=payload,
            headers=headers,
        )
        return self._parse_statistics_response(response.json())

    def get_latest(
        self,
        *,
        bbox: BBox,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        max_cloud: int = DEFAULT_MAX_CLOUD,
    ) -> NdviPoint | None:
        today = date.today()
        start = today - timedelta(days=lookback_days)
        points = self.get_timeseries(
            bbox=bbox,
            start=start,
            end=today,
            step_days=lookback_days,
            max_cloud=max_cloud,
        )
        if not points:
            return None
        return sorted(points, key=lambda p: p.date)[-1]

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        max_attempts: int = 3,
    ) -> httpx.Response:
        attempt = 0
        last_error: Exception | None = None
        while attempt < max_attempts:
            attempt += 1
            started = time.monotonic()
            try:
                response = self._http.request(
                    method,
                    url,
                    json=json,
                    data=data,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                ndvi_upstream_latency_seconds.labels(
                    engine=self.engine_name
                ).observe(time.monotonic() - started)
                response.raise_for_status()
                ndvi_upstream_requests_total.labels(
                    engine=self.engine_name, outcome="success"
                ).inc()
                return response
            except httpx.HTTPStatusError as exc:
                last_error = exc
                ndvi_upstream_requests_total.labels(
                    engine=self.engine_name, outcome="error"
                ).inc()
                if exc.response.status_code >= 500 and attempt < max_attempts:
                    time.sleep(0.5 * attempt)
                    continue
                raise
            except httpx.RequestError as exc:
                last_error = exc
                ndvi_upstream_requests_total.labels(
                    engine=self.engine_name, outcome="network"
                ).inc()
                if attempt < max_attempts:
                    time.sleep(0.5 * attempt)
                    continue
                raise
        if last_error:
            raise last_error
        raise RuntimeError("Unknown upstream error")

    def _get_access_token(self) -> str:
        key = f"ndvi:sentinelhub:token:{self.client_id}"
        cached = self.cache.get(key)
        if cached:
            ndvi_cache_hit_total.labels(layer="sentinel_token").inc()
            return str(cached)

        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = self._request_with_retry(
            "POST",
            self.token_url,
            json=None,
            data=data,
            headers=headers,
        )
        token_data = response.json()
        token = token_data.get("access_token")
        expires_in = int(token_data.get("expires_in", 3600))
        if not token:
            raise ValueError(
                "Sentinel Hub token response missing access_token"
            )

        ttl = max(expires_in - 60, 60)
        self.cache.set(key, token, ttl)
        return str(token)

    def _build_statistics_payload(
        self,
        *,
        bbox: BBox,
        start: date,
        end: date,
        step_days: int,
        max_cloud: int,
    ) -> dict[str, Any]:
        bounds = [
            float(bbox.west),
            float(bbox.south),
            float(bbox.east),
            float(bbox.north),
        ]
        payload: dict[str, Any] = {
            "input": {
                "bounds": {"bbox": bounds},
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "dataFilter": {
                            "maxCloudCoverage": max_cloud,
                        },
                    }
                ],
            },
            "aggregation": {
                "timeRange": {
                    "from": datetime.combine(
                        start, datetime.min.time()
                    ).isoformat()
                    + "Z",
                    "to": datetime.combine(
                        end, datetime.max.time()
                    ).isoformat()
                    + "Z",
                },
                "aggregationInterval": {"of": f"P{int(step_days)}D"},
                "evalscript": NDVI_EVALSCRIPT,
            },
            "calculations": {"default": {}},
        }
        logger.debug("sentinelhub.request payload=%s", json.dumps(payload))
        return payload

    def _parse_statistics_response(
        self, data: dict[str, Any]
    ) -> list[NdviPoint]:
        buckets: list[NdviPoint] = []
        for item in data.get("data", []):
            interval = item.get("interval", {})
            raw_from = interval.get("from") or interval.get("date")
            if not raw_from:
                continue
            try:
                bucket_date = date.fromisoformat(str(raw_from)[:10])
            except ValueError:
                continue

            outputs = item.get("outputs", {}).get("default", {})
            stats_container = (
                outputs.get("statistics") or outputs.get("bands") or {}
            )
            ndvi_stats: dict[str, Any] | None = None
            if isinstance(stats_container, dict):
                ndvi_stats = (
                    stats_container.get("ndvi")
                    or stats_container.get("NDVI")
                    or stats_container
                )
            raw_stats: dict[str, Any] = {}
            if isinstance(ndvi_stats, dict):
                raw_stats = cast(
                    dict[str, Any], ndvi_stats.get("stats") or ndvi_stats
                )

            mean_val = raw_stats.get("mean")
            if mean_val is None:
                continue
            try:
                mean = float(mean_val)
            except (TypeError, ValueError):
                continue

            min_val = raw_stats.get("min")
            max_val = raw_stats.get("max")
            sample_count = raw_stats.get("sampleCount") or raw_stats.get(
                "count"
            )
            cloud_fraction = outputs.get("cloudCoverage") or outputs.get(
                "cloudFraction"
            )

            buckets.append(
                NdviPoint(
                    date=bucket_date,
                    mean=mean,
                    min=float(min_val) if min_val is not None else None,
                    max=float(max_val) if max_val is not None else None,
                    sample_count=(
                        int(sample_count) if sample_count is not None else None
                    ),
                    cloud_fraction=(
                        float(cloud_fraction)
                        if cloud_fraction is not None
                        else None
                    ),
                )
            )
        return buckets

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return (
            "SentinelHubEngine("
            f"client_id={self.client_id}, base_url={self.base_url}, "
            f"timeout={self.timeout_seconds}"
            ")"
        )
