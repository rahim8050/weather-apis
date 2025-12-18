from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from .models import Farm


class IsFarmOwner(BasePermission):
    def has_object_permission(
        self, request: Request, view: APIView, obj: object
    ) -> bool:
        if not isinstance(obj, Farm):
            return False
        return bool(
            request.user and obj.owner_id == getattr(request.user, "id", None)
        )
