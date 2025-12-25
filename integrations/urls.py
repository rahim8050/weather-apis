# Routes (prefix: /api/v1/):
# - GET /integrations/nextcloud/ping/ -> NextcloudPingView

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    IntegrationClientViewSet,
    IntegrationPingView,
    NextcloudPingView,
)

router = DefaultRouter()
router.register(
    r"clients",
    IntegrationClientViewSet,
    basename="integration-client",
)

urlpatterns = [
    path(
        "nextcloud/ping/",
        NextcloudPingView.as_view(),
        name="nextcloud-hmac",
    ),
    path(
        "integrations/nextcloud/ping/",
        NextcloudPingView.as_view(),
        name="nextcloud-ping",
    ),
    path("ping/", IntegrationPingView.as_view(), name="integration-ping"),
] + router.urls
