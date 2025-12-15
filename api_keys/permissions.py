from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from .auth import get_header_key


class HasValidApiKey(BasePermission):
    message = "Invalid API key."

    def has_permission(self, request: Request, view: object) -> bool:
        raw_key = get_header_key(request)
        if not raw_key:
            return False
        return True
