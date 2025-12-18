from __future__ import annotations

from datetime import date
from typing import Any, cast

from rest_framework import serializers

from .models import NdviJob, NdviObservation
from .services import normalize_latest_params, normalize_timeseries_params


class NdviObservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = NdviObservation
        fields = [
            "bucket_date",
            "mean",
            "min",
            "max",
            "sample_count",
            "cloud_fraction",
        ]


class TimeseriesRequestSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    step_days = serializers.IntegerField(
        required=False, min_value=1, max_value=30
    )
    max_cloud = serializers.IntegerField(
        required=False, min_value=0, max_value=100
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        params = normalize_timeseries_params(
            start=cast(date, attrs["start"]),
            end=cast(date, attrs["end"]),
            step_days=cast(int | None, attrs.get("step_days")),
            max_cloud=cast(int | None, attrs.get("max_cloud")),
        )
        return {
            "start": params.start,
            "end": params.end,
            "step_days": params.step_days,
            "max_cloud": params.max_cloud,
        }


class LatestRequestSerializer(serializers.Serializer):
    lookback_days = serializers.IntegerField(required=False, min_value=1)
    max_cloud = serializers.IntegerField(
        required=False, min_value=0, max_value=100
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        params = normalize_latest_params(
            lookback_days=cast(int | None, attrs.get("lookback_days")),
            max_cloud=cast(int | None, attrs.get("max_cloud")),
        )
        return {
            "lookback_days": params.lookback_days,
            "max_cloud": params.max_cloud,
        }


class NdviJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = NdviJob
        fields = [
            "id",
            "job_type",
            "status",
            "start",
            "end",
            "step_days",
            "max_cloud",
            "lookback_days",
            "created_at",
            "started_at",
            "finished_at",
            "attempts",
            "last_error",
        ]
        read_only_fields = fields
