from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import ClassVar

from django.conf import settings
from rest_framework import serializers

from config.api.responses import JSONValue

from .timeutils import get_zone, isoformat_with_tz

DEFAULT_TZ = getattr(settings, "WEATHER_DEFAULT_TZ", "Africa/Nairobi")
MAX_RANGE_DAYS = int(getattr(settings, "WEATHER_MAX_RANGE_DAYS", 366))


class BaseWeatherParamsSerializer(serializers.Serializer):
    lat: ClassVar[serializers.FloatField] = serializers.FloatField(
        min_value=-90.0, max_value=90.0
    )
    lon: ClassVar[serializers.FloatField] = serializers.FloatField(
        min_value=-180.0, max_value=180.0
    )
    tz: ClassVar[serializers.CharField] = serializers.CharField(
        required=False, default=DEFAULT_TZ
    )
    provider: ClassVar[serializers.CharField] = serializers.CharField(
        required=False, allow_null=True
    )

    def _allowed_providers(self) -> Iterable[str]:
        return ("open_meteo", "nasa_power")

    def validate_tz(self, value: str) -> str:
        try:
            get_zone(value)
        except ValueError as exc:
            raise serializers.ValidationError("Invalid timezone.") from exc
        return value

    def validate_provider(self, value: str | None) -> str | None:
        if value is None:
            return None
        if value == "":
            return None
        normalized = value.lower()
        if normalized not in self._allowed_providers():
            raise serializers.ValidationError("Unknown provider.")
        return normalized


class RangeWeatherParamsSerializer(BaseWeatherParamsSerializer):
    start: ClassVar[serializers.DateField] = serializers.DateField()
    end: ClassVar[serializers.DateField] = serializers.DateField()

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        attrs = super().validate(attrs)
        start = attrs.get("start")
        end = attrs.get("end")
        if isinstance(start, date) and isinstance(end, date):
            if start > end:
                raise serializers.ValidationError(
                    "start must be on or before end."
                )
            delta_days = (end - start).days
            if delta_days > MAX_RANGE_DAYS:
                raise serializers.ValidationError(
                    "Requested range exceeds WEATHER_MAX_RANGE_DAYS."
                )
        return attrs


class CurrentWeatherSerializer(serializers.Serializer):
    observed_at: ClassVar[serializers.DateTimeField] = (
        serializers.DateTimeField()
    )
    temperature_c: ClassVar[serializers.FloatField] = serializers.FloatField(
        allow_null=True
    )
    wind_speed_mps: ClassVar[serializers.FloatField] = serializers.FloatField(
        allow_null=True
    )
    source: ClassVar[serializers.CharField] = serializers.CharField()  # type: ignore[misc,assignment]


class DailyForecastSerializer(serializers.Serializer):
    day: ClassVar[serializers.DateField] = serializers.DateField()
    t_min_c: ClassVar[serializers.FloatField] = serializers.FloatField(
        allow_null=True
    )
    t_max_c: ClassVar[serializers.FloatField] = serializers.FloatField(
        allow_null=True
    )
    precipitation_mm: ClassVar[serializers.FloatField] = (
        serializers.FloatField(allow_null=True)
    )
    source: ClassVar[serializers.CharField] = serializers.CharField()  # type: ignore[misc,assignment]


class WeeklyReportSerializer(serializers.Serializer):
    week_start: ClassVar[serializers.DateField] = serializers.DateField()
    week_end: ClassVar[serializers.DateField] = serializers.DateField()
    t_min_avg_c: ClassVar[serializers.FloatField] = serializers.FloatField(
        allow_null=True
    )
    t_max_avg_c: ClassVar[serializers.FloatField] = serializers.FloatField(
        allow_null=True
    )
    precipitation_sum_mm: ClassVar[serializers.FloatField] = (
        serializers.FloatField(allow_null=True)
    )
    days: ClassVar[DailyForecastSerializer] = DailyForecastSerializer(
        many=True
    )
    source: ClassVar[serializers.CharField] = serializers.CharField()  # type: ignore[misc,assignment]


def serialize_current(payload: object) -> dict[str, JSONValue]:
    serializer = CurrentWeatherSerializer(payload)
    data = serializer.data
    observed_attr = getattr(payload, "observed_at", None)
    if isinstance(observed_attr, datetime):
        data["observed_at"] = isoformat_with_tz(observed_attr)
    return data


def serialize_daily(
    forecasts: Sequence[object],
) -> list[dict[str, JSONValue]]:
    serializer = DailyForecastSerializer(forecasts, many=True)
    return list(serializer.data)


def serialize_weekly(
    reports: Sequence[object],
) -> list[dict[str, JSONValue]]:
    serializer = WeeklyReportSerializer(reports, many=True)
    return list(serializer.data)
