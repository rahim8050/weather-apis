from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from .auth import get_header_key, validate_api_key
from .models import ApiKey, ApiKeyScope


class HasValidApiKey(BasePermission):
    message = "Invalid API key."

    def has_permission(self, request: Request, view: object) -> bool:
        raw_key = get_header_key(request)
        if not raw_key:
            return False
        return validate_api_key(raw_key) is not None


class ApiKeyScopePermission(BasePermission):
    """Restrict unsafe HTTP methods based on the ApiKey scope.

    This permission is intended to be combined with authentication/permission
    classes like `IsAuthenticated`. It only applies restrictions when the
    request is authenticated via an `ApiKey` (i.e., `request.auth` is an
    `ApiKey` instance). JWT-authenticated requests pass unchanged.
    """

    message = "API key scope does not permit this action."

    def has_permission(self, request: Request, view: object) -> bool:
        auth = getattr(request, "auth", None)
        if not isinstance(auth, ApiKey):
            return True

        if auth.scope == ApiKeyScope.ADMIN:
            return True

        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return auth.scope in {ApiKeyScope.READ, ApiKeyScope.WRITE}

        return auth.scope == ApiKeyScope.WRITE
