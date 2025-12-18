from __future__ import annotations

from django.urls import path

from .views import (
    NdviJobStatusView,
    NdviLatestView,
    NdviRefreshView,
    NdviTimeseriesView,
)

urlpatterns = [
    path(
        "farms/<int:farm_id>/ndvi/timeseries/",
        NdviTimeseriesView.as_view(),
        name="ndvi-timeseries",
    ),
    path(
        "farms/<int:farm_id>/ndvi/latest/",
        NdviLatestView.as_view(),
        name="ndvi-latest",
    ),
    path(
        "farms/<int:farm_id>/ndvi/refresh/",
        NdviRefreshView.as_view(),
        name="ndvi-refresh",
    ),
    path(
        "ndvi/jobs/<int:job_id>/",
        NdviJobStatusView.as_view(),
        name="ndvi-job",
    ),
]
