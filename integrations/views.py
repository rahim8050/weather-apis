"""Integration endpoints (e.g., Nextcloud).

Authentication: endpoints may override global auth to support
service-to-service integration flows. Global defaults remain JWT + API key.

All successful responses from these endpoints use the project envelope produced
by `config.api.responses.success_response`:

    {"status": 0, "message": "<str>", "data": <object|null>, "errors": null}
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api_keys.authentication import ApiKeyAuthentication
from api_keys.throttling import ApiKeyRateThrottle
from config.api.openapi import (
    error_envelope_serializer,
    success_envelope_serializer,
)
from config.api.responses import success_response

from .hmac import (
    NEXTCLOUD_CLIENT_ID_HEADER,
    NEXTCLOUD_NONCE_HEADER,
    NEXTCLOUD_SIGNATURE_HEADER,
    NEXTCLOUD_TIMESTAMP_HEADER,
)
from .permissions import NextcloudHMACPermission

nextcloud_ping_data_schema = inline_serializer(
    name="NextcloudPingData",
    fields={
        "ok": serializers.BooleanField(),
        "client_id": serializers.CharField(),
    },
)
nextcloud_ping_success_schema = success_envelope_serializer(
    "NextcloudPingSuccessResponse",
    data=nextcloud_ping_data_schema,
)
nextcloud_ping_error_schema = error_envelope_serializer(
    "NextcloudPingErrorResponse"
)


@extend_schema(auth=[])
class NextcloudPingView(APIView):
    """Verify Nextcloud request signing (HMAC) configuration.

    Authentication: none (overrides global JWT/API key auth).
    Permissions: `NextcloudHMACPermission` only.
    Throttling: global DRF throttles (anon/user/api_key/scoped).
    Response data: `{"ok": true, "client_id": "<client_id>"}`.
    """

    authentication_classes = ()
    permission_classes = (NextcloudHMACPermission,)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name=NEXTCLOUD_CLIENT_ID_HEADER,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description="Nextcloud instance public identifier.",
            ),
            OpenApiParameter(
                name=NEXTCLOUD_TIMESTAMP_HEADER,
                type=OpenApiTypes.INT,
                location=OpenApiParameter.HEADER,
                required=True,
                description="Unix timestamp (seconds).",
            ),
            OpenApiParameter(
                name=NEXTCLOUD_NONCE_HEADER,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description="Unique per-request nonce.",
            ),
            OpenApiParameter(
                name=NEXTCLOUD_SIGNATURE_HEADER,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description="Hex HMAC-SHA256 of canonical request string.",
            ),
        ],
        responses={
            200: nextcloud_ping_success_schema,
            403: nextcloud_ping_error_schema,
        },
    )
    def get(self, request: Request) -> Response:  # type: ignore[override]
        """Return `ok` + verified `client_id` if HMAC validation succeeds.

        Inputs: signature headers (X-NC-CLIENT-ID, X-NC-TIMESTAMP, X-NC-NONCE,
        X-NC-SIGNATURE).
        Output: success envelope with `data.ok` and `data.client_id`.
        Side effects: stores the nonce in the configured cache for replay
        protection.
        """

        client_id = getattr(request, "nc_hmac_client_id", "")
        return success_response({"ok": True, "client_id": client_id})


class IntegrationPingView(APIView):
    authentication_classes = (ApiKeyAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (ApiKeyRateThrottle,)

    def get(self, request: Request) -> Any:
        auth_obj = request.auth
        key_id = getattr(auth_obj, "id", None)
        scope = getattr(auth_obj, "scope", None)

        data: dict[str, Any] = {
            "ok": True,
            "auth": "api_key",
            "user_id": str(request.user.pk),
            "key_id": str(key_id) if key_id is not None else None,
            "scope": str(scope) if scope is not None else None,
            "server_time": timezone.now().isoformat(),
        }
        return success_response(data, message="pong")
