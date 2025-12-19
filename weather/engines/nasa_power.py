from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx
from django.conf import settings
from django.utils import timezone as dj_timezone

from ..timeutils import ensure_aware, get_zone, local_day_bounds_to_utc
from .base import WeatherProvider
from .types import CurrentWeather, DailyForecast, Location, ProviderName


class NasaPowerProvider(WeatherProvider):
    """NASA POWER daily point provider.

    The API returns daily aggregates only; `current` returns the most recent
    daily value from a small local-day window (today and yesterday).
    """

    name: ProviderName = "nasa_power"
    _PARAMS = "T2M_MIN,T2M_MAX,PRECTOTCORR"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url: str = base_url or cast(
            str,
            getattr(
                settings,
                "NASA_POWER_BASE_URL",
                "https://power.larc.nasa.gov/api/temporal/daily/point",
            ),
        )
        self.timeout = timeout

    async def current(self, loc: Location) -> CurrentWeather:
        zone = get_zone(loc.tz)
        today = dj_timezone.localtime(dj_timezone.now(), zone).date()
        start = today - timedelta(days=1)
        forecasts = await self.daily(loc, start, today)
        latest = max(forecasts, key=lambda f: f.day, default=None)

        observed_day = latest.day if latest else today
        observed_at = ensure_aware(
            datetime.combine(observed_day, time.min), zone
        )

        temperature = self._choose_temperature(latest)
        return CurrentWeather(
            observed_at=observed_at,
            temperature_c=temperature,
            wind_speed_mps=None,
            source=self.name,
        )

    async def daily(
        self, loc: Location, start: date, end: date
    ) -> Sequence[DailyForecast]:
        zone = get_zone(loc.tz)
        start_utc, _ = local_day_bounds_to_utc(start, zone)
        _, end_utc = local_day_bounds_to_utc(end, zone)
        params = {
            "latitude": loc.lat,
            "longitude": loc.lon,
            "start": self._format_yyyymmdd(start_utc.date()),
            "end": self._format_yyyymmdd(end_utc.date()),
            "time-standard": "UTC",
            "parameters": self._PARAMS,
            "format": "JSON",
        }
        response = await self._request(params)
        properties = (
            response.get("properties", {})
            if isinstance(response, dict)
            else {}
        )
        fill_value = properties.get("fill_value", -999)
        parameters = (
            properties.get("parameter", {})
            if isinstance(properties, dict)
            else {}
        )

        tmin_data = parameters.get("T2M_MIN") or {}
        tmax_data = parameters.get("T2M_MAX") or {}
        precip_data = parameters.get("PRECTOTCORR") or {}

        day_keys: set[str] = set()
        for container in (tmin_data, tmax_data, precip_data):
            if isinstance(container, dict):
                day_keys.update(container.keys())

        forecasts: list[DailyForecast] = []
        for key in sorted(day_keys):
            local_day = self._parse_day_to_local(key, zone)
            if local_day is None:
                continue
            t_min = self._extract_value(tmin_data, key, fill_value)
            t_max = self._extract_value(tmax_data, key, fill_value)
            precipitation = self._extract_value(precip_data, key, fill_value)
            forecasts.append(
                DailyForecast(
                    day=local_day,
                    t_min_c=t_min,
                    t_max_c=t_max,
                    precipitation_mm=precipitation,
                    source=self.name,
                )
            )
        return forecasts

    async def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(self.base_url, params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected NASA POWER response shape")
        return data

    def _parse_day_to_local(self, raw: str, zone: ZoneInfo) -> date | None:
        try:
            utc_day = datetime.strptime(raw, "%Y%m%d").replace(
                tzinfo=timezone.utc  # noqa: UP017
            )
        except ValueError:
            return None
        return utc_day.astimezone(zone).date()

    def _extract_value(
        self, container: Any, key: str, fill_value: Any
    ) -> float | None:
        if not isinstance(container, dict):
            return None
        raw = container.get(key)
        if raw is None:
            return None
        try:
            if raw == fill_value or float(raw) == float(fill_value):
                return None
        except (TypeError, ValueError):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _choose_temperature(
        self, latest: DailyForecast | None
    ) -> float | None:
        if latest is None:
            return None
        if latest.t_min_c is not None and latest.t_max_c is not None:
            return (latest.t_min_c + latest.t_max_c) / 2
        if latest.t_max_c is not None:
            return latest.t_max_c
        return latest.t_min_c

    def _format_yyyymmdd(self, value: date) -> str:
        return value.strftime("%Y%m%d")
