# Routes (prefix: /api/v1/):
# - GET /integrations/nextcloud/ping/ -> NextcloudPingView

from django.urls import path

from .views import IntegrationPingView, NextcloudPingView

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
]
