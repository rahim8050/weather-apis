"""DRF permissions for Nextcloud HMAC request signing.

These permissions are designed to be composed with existing JWT and API key
auth without changing the global authentication stack.
"""

from __future__ import annotations

from typing import Any, cast

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from .hmac import NextcloudHMACVerificationError, verify_nextcloud_hmac_request

INTEGRATION_HMAC_NONCE_TTL_SECONDS = 600


def _permission_detail(
    exc: NextcloudHMACVerificationError,
) -> dict[str, str]:
    return {
        "detail": "Invalid Nextcloud signature",
        "code": exc.code,
        "reason": str(exc),
    }


class NextcloudHMACPermission(BasePermission):
    """Require a valid Nextcloud instance HMAC signature.

    When valid, sets `request.nc_hmac_client_id` for downstream use.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        try:
            client_id = verify_nextcloud_hmac_request(request)
        except NextcloudHMACVerificationError as exc:
            raise PermissionDenied(_permission_detail(exc)) from exc

        cast(Any, request).nc_hmac_client_id = client_id
        return True


class IntegrationHMACPermission(BasePermission):
    """Require a valid integration HMAC signature for token bootstrap.

    When valid, sets `request.nc_hmac_client_id` for downstream use.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        try:
            client_id = verify_nextcloud_hmac_request(
                request,
                nonce_ttl_seconds=INTEGRATION_HMAC_NONCE_TTL_SECONDS,
            )
        except NextcloudHMACVerificationError as exc:
            raise PermissionDenied(_permission_detail(exc)) from exc

        cast(Any, request).nc_hmac_client_id = client_id
        return True
