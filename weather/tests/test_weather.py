from __future__ import annotations

# ruff: noqa: S101
import asyncio
from datetime import date, datetime, timezone

import httpx
import pytest
from django.conf import LazySettings
from django.core.cache import caches
from django.utils import timezone as dj_timezone

from weather.engines.nasa_power import NasaPowerProvider
from weather.engines.open_meteo import OpenMeteoProvider
from weather.engines.types import DailyForecast, Location
from weather.metrics import (
    weather_cache_hits_total,
    weather_cache_misses_total,
    weather_provider_errors_total,
    weather_provider_requests_total,
)
from weather.serializers import serialize_current
from weather.services import (
    DEFAULT_TZ,
    _aggregate_weekly,
    get_current_weather,
    get_daily_forecast,
)


def _clear_cache() -> None:
    caches["default"].clear()


def test_open_meteo_current_parses_observed_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cache()
    payload: dict[str, object] = {
        "current": {
            "time": "2025-01-02T10:00",
            "temperature_2m": 24.2,
            "wind_speed_10m": 3.5,
        }
    }

    async def fake_request(
        self: OpenMeteoProvider, params: dict[str, object]
    ) -> dict[str, object]:
        return payload

    monkeypatch.setattr(OpenMeteoProvider, "_request", fake_request)
    result = asyncio.run(
        get_current_weather(
            lat=1.0,
            lon=36.0,
            tz="Africa/Nairobi",
            provider="open_meteo",
        )
    )
    serialized = serialize_current(result)
    assert serialized["temperature_c"] == pytest.approx(24.2)
    assert serialized["wind_speed_mps"] == pytest.approx(3.5)
    assert str(serialized["observed_at"]).endswith("+03:00")


def test_nasa_power_daily_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cache()
    payload: dict[str, object] = {
        "properties": {
            "parameter": {
                "T2M_MIN": {"20250101": 20.0},
                "T2M_MAX": {"20250101": 30.0},
                "PRECTOTCORR": {"20250101": -999, "20250102": 5.0},
            },
            "fill_value": -999,
        }
    }

    async def fake_request(
        self: NasaPowerProvider, params: dict[str, object]
    ) -> dict[str, object]:
        return payload

    monkeypatch.setattr(NasaPowerProvider, "_request", fake_request)
    provider = NasaPowerProvider()
    forecasts = asyncio.run(
        provider.daily(
            Location(lat=1.0, lon=36.0, tz="Africa/Nairobi"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )
    )
    assert len(forecasts) == 2
    first = forecasts[0]
    assert first.day == date(2025, 1, 1)
    assert first.t_min_c == pytest.approx(20.0)
    assert first.t_max_c == pytest.approx(30.0)
    assert first.precipitation_mm is None
    second = forecasts[1]
    assert second.precipitation_mm == pytest.approx(5.0)


def test_open_meteo_daily_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cache()
    payload: dict[str, object] = {
        "daily": {
            "time": ["2025-02-01", "invalid"],
            "temperature_2m_min": [12.0, 13.0],
            "temperature_2m_max": [22.0, None],
            "precipitation_sum": [0.5, 1.0],
        }
    }

    async def fake_request(
        self: OpenMeteoProvider, params: dict[str, object]
    ) -> dict[str, object]:
        return payload

    monkeypatch.setattr(OpenMeteoProvider, "_request", fake_request)
    provider = OpenMeteoProvider()
    forecasts = asyncio.run(
        provider.daily(
            Location(lat=1.0, lon=36.0, tz="Africa/Nairobi"),
            date(2025, 2, 1),
            date(2025, 2, 2),
        )
    )
    assert len(forecasts) == 1
    forecast = forecasts[0]
    assert forecast.day == date(2025, 2, 1)
    assert forecast.t_min_c == pytest.approx(12.0)
    assert forecast.t_max_c == pytest.approx(22.0)
    assert forecast.precipitation_mm == pytest.approx(0.5)
    assert forecast.source == "open_meteo"


def test_provider_switching_default_and_override(
    monkeypatch: pytest.MonkeyPatch, settings: LazySettings
) -> None:
    _clear_cache()
    settings.WEATHER_PROVIDER_DEFAULT = "open_meteo"
    open_payload: dict[str, object] = {
        "current": {
            "time": "2025-02-01T08:00",
            "temperature_2m": 22.0,
            "wind_speed_10m": 4.0,
        }
    }
    nasa_payload: dict[str, object] = {
        "properties": {
            "parameter": {
                "T2M_MIN": {"20250201": 18.0},
                "T2M_MAX": {"20250201": 28.0},
                "PRECTOTCORR": {"20250201": 2.0},
            },
            "fill_value": -999,
        }
    }

    async def fake_open(
        self: OpenMeteoProvider, params: dict[str, object]
    ) -> dict[str, object]:
        return open_payload

    async def fake_nasa(
        self: NasaPowerProvider, params: dict[str, object]
    ) -> dict[str, object]:
        return nasa_payload

    monkeypatch.setattr(OpenMeteoProvider, "_request", fake_open)
    monkeypatch.setattr(NasaPowerProvider, "_request", fake_nasa)
    monkeypatch.setattr(
        dj_timezone,
        "now",
        lambda: datetime(
            2025,
            2,
            1,
            tzinfo=timezone.utc,  # noqa: UP017
        ),
    )

    default_result = asyncio.run(
        get_current_weather(lat=0.5, lon=36.8, tz=DEFAULT_TZ)
    )
    assert default_result.source == "open_meteo"

    nasa_result = asyncio.run(
        get_current_weather(
            lat=0.5,
            lon=36.8,
            tz=DEFAULT_TZ,
            provider="nasa_power",
        )
    )
    assert nasa_result.source == "nasa_power"
    assert nasa_result.temperature_c == pytest.approx(23.0)


def test_weekly_bucketing_monday_to_sunday() -> None:
    forecasts = [
        DailyForecast(
            day=date(2025, 1, 6),
            t_min_c=10.0,
            t_max_c=20.0,
            precipitation_mm=1.0,
            source="open_meteo",
        ),
        DailyForecast(
            day=date(2025, 1, 7),
            t_min_c=None,
            t_max_c=22.0,
            precipitation_mm=2.0,
            source="open_meteo",
        ),
        DailyForecast(
            day=date(2025, 1, 12),
            t_min_c=12.0,
            t_max_c=None,
            precipitation_mm=0.5,
            source="open_meteo",
        ),
        DailyForecast(
            day=date(2025, 1, 13),
            t_min_c=9.0,
            t_max_c=19.0,
            precipitation_mm=0.0,
            source="open_meteo",
        ),
    ]

    reports = _aggregate_weekly(forecasts, "open_meteo")
    assert len(reports) == 2
    first = reports[0]
    assert first.week_start == date(2025, 1, 6)
    assert first.week_end == date(2025, 1, 12)
    assert first.t_min_avg_c == pytest.approx((10.0 + 12.0) / 2)
    assert first.t_max_avg_c == pytest.approx((20.0 + 22.0) / 2)
    assert first.precipitation_sum_mm == pytest.approx(3.5)
    second = reports[1]
    assert second.week_start == date(2025, 1, 13)
    assert second.precipitation_sum_mm == pytest.approx(0.0)


def test_cache_hits_and_misses_increment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_cache()

    async def fake_daily(
        self: OpenMeteoProvider, loc: Location, start: date, end: date
    ) -> list[DailyForecast]:
        return [
            DailyForecast(
                day=start,
                t_min_c=15.0,
                t_max_c=25.0,
                precipitation_mm=1.0,
                source="open_meteo",
            )
        ]

    monkeypatch.setattr(OpenMeteoProvider, "daily", fake_daily)
    miss_counter = weather_cache_misses_total.labels(
        provider="open_meteo", endpoint="daily"
    )
    hit_counter = weather_cache_hits_total.labels(
        provider="open_meteo", endpoint="daily"
    )
    request_counter = weather_provider_requests_total.labels(
        provider="open_meteo", endpoint="daily"
    )
    misses_before = miss_counter._value.get()
    hits_before = hit_counter._value.get()
    requests_before = request_counter._value.get()

    first = asyncio.run(
        get_daily_forecast(
            lat=1.1,
            lon=36.9,
            start=date(2025, 3, 1),
            end=date(2025, 3, 1),
            tz=DEFAULT_TZ,
        )
    )
    second = asyncio.run(
        get_daily_forecast(
            lat=1.1,
            lon=36.9,
            start=date(2025, 3, 1),
            end=date(2025, 3, 1),
            tz=DEFAULT_TZ,
        )
    )
    assert first == second

    misses_after = miss_counter._value.get()
    hits_after = hit_counter._value.get()
    requests_after = request_counter._value.get()
    assert misses_after == misses_before + 1
    assert hits_after == hits_before + 1
    assert requests_after == requests_before + 1


def test_error_metrics_increment(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_cache()
    error = httpx.HTTPStatusError(
        "boom",
        request=httpx.Request("GET", "https://example.com"),
        response=httpx.Response(503),
    )

    async def failing_daily(*_: object, **__: object) -> None:
        raise error

    monkeypatch.setattr(OpenMeteoProvider, "daily", failing_daily)
    error_counter = weather_provider_errors_total.labels(
        provider="open_meteo", endpoint="daily", error_type="HTTPStatusError"
    )
    before = error_counter._value.get()
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            get_daily_forecast(
                lat=2.0,
                lon=37.1,
                start=date(2025, 4, 1),
                end=date(2025, 4, 1),
                tz=DEFAULT_TZ,
            )
        )
    after = error_counter._value.get()
    assert after == before + 1
