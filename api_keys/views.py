"""API key lifecycle management endpoints.

All successful responses are wrapped by
`config.api.responses.success_response`:

    {"status": 0, "message": "<str>", "data": <object|null>, "errors": null}
"""

from __future__ import annotations

import logging
from typing import cast

from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from config.api.openapi import (
    error_envelope_serializer,
    success_envelope_serializer,
)
from config.api.responses import success_response

from .models import ApiKey, ApiKeyScope
from .serializers import ApiKeyCreateSerializer, ApiKeyListSerializer

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        parts = str(forwarded_for).split(",")
        if parts:
            return parts[0].strip() or None
    remote_addr = request.META.get("REMOTE_ADDR")
    return str(remote_addr) if remote_addr else None


api_keys_error_response = error_envelope_serializer("ApiKeysErrorResponse")
api_key_list_success_response = success_envelope_serializer(
    "ApiKeyListSuccessResponse",
    data=ApiKeyListSerializer(many=True),
)
api_key_create_success_response = success_envelope_serializer(
    "ApiKeyCreateSuccessResponse",
    data=ApiKeyCreateSerializer(),
)
api_key_revoke_success_response = success_envelope_serializer(
    "ApiKeyRevokeSuccessResponse",
    data=serializers.JSONField(allow_null=True),
)

api_key_rotate_data_schema = inline_serializer(
    name="ApiKeyRotateData",
    fields={
        "id": serializers.UUIDField(),
        "name": serializers.CharField(),
        "scope": serializers.ChoiceField(choices=ApiKeyScope.values),
        "prefix": serializers.CharField(),
        "last4": serializers.CharField(),
        "created_at": serializers.DateTimeField(),
        "expires_at": serializers.DateTimeField(allow_null=True),
        "revoked_at": serializers.DateTimeField(allow_null=True),
        "api_key": serializers.CharField(allow_null=True),
    },
)
api_key_rotate_success_response = success_envelope_serializer(
    "ApiKeyRotateSuccessResponse",
    data=api_key_rotate_data_schema,
)


@extend_schema(auth=cast(list[str], [{"BearerAuth": []}]))
class ApiKeyView(generics.GenericAPIView):
    """List and create API keys for the authenticated user.

    Authentication: BearerAuth (JWT).
    Permissions: IsAuthenticated.
    GET response: success envelope with a list of `ApiKeyListSerializer`.
    POST request: `ApiKeyCreateSerializer`.
    POST response: success envelope with `ApiKeyCreateSerializer` data.
    """

    authentication_classes = (JWTAuthentication,)
    serializer_class = ApiKeyListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[ApiKey]:
        user = self.request.user
        if isinstance(user, AnonymousUser):
            return ApiKey.objects.none()
        return ApiKey.objects.filter(user=user)

    def get_serializer_class(self) -> type[Serializer]:
        if self.request.method == "GET":
            return ApiKeyListSerializer
        return ApiKeyCreateSerializer

    @extend_schema(
        responses={
            200: api_key_list_success_response,
            401: api_keys_error_response,
        }
    )
    def get(self, request: Request) -> Response:
        """Return all API keys belonging to the authenticated user."""
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(serializer.data, message="API keys")

    @extend_schema(
        request=ApiKeyCreateSerializer,
        responses={
            201: api_key_create_success_response,
            400: api_keys_error_response,
            401: api_keys_error_response,
        },
    )
    def post(self, request: Request) -> Response:
        """Create a new API key for the authenticated user."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        api_key = serializer.save()
        logger.info(
            "api_key.created user_id=%s key_id=%s scope=%s path=%s method=%s "
            "status_code=%s ip=%s ua=%s",
            getattr(request.user, "id", None),
            getattr(api_key, "id", None),
            getattr(api_key, "scope", None),
            getattr(request, "path", ""),
            getattr(request, "method", ""),
            status.HTTP_201_CREATED,
            _client_ip(request),
            request.META.get("HTTP_USER_AGENT"),
        )
        out = self.get_serializer(api_key).data
        return success_response(
            out,
            message="API key created",
            status_code=status.HTTP_201_CREATED,
        )


@extend_schema(auth=cast(list[str], [{"BearerAuth": []}]))
class ApiKeyRevokeView(APIView):
    """Revoke an existing API key.

    Authentication: BearerAuth (JWT).
    Permissions: IsAuthenticated.
    Request body: none.
    Success response: success envelope with `data = null`.
    """

    authentication_classes = (JWTAuthentication,)
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: api_key_revoke_success_response,
            401: api_keys_error_response,
            403: api_keys_error_response,
            404: api_keys_error_response,
        }
    )
    def delete(self, request: Request, pk: str) -> Response:
        """Revoke the API key identified by `pk`."""
        api_key = get_object_or_404(ApiKey, pk=pk)

        if api_key.user != request.user:
            raise PermissionDenied(
                "You do not have permission to revoke this key."
            )

        if api_key.revoked_at is None:
            api_key.revoked_at = timezone.now()
            api_key.save(update_fields=["revoked_at"])
            already_revoked = False
        else:
            already_revoked = True

        logger.info(
            "api_key.revoked user_id=%s key_id=%s already_revoked=%s path=%s "
            "method=%s status_code=%s ip=%s ua=%s",
            getattr(request.user, "id", None),
            getattr(api_key, "id", None),
            already_revoked,
            getattr(request, "path", ""),
            getattr(request, "method", ""),
            status.HTTP_200_OK,
            _client_ip(request),
            request.META.get("HTTP_USER_AGENT"),
        )

        return success_response(None, message="API key revoked")


@extend_schema(auth=cast(list[str], [{"BearerAuth": []}]))
class ApiKeyRotateView(APIView):
    """Rotate an API key by revoking the existing key and creating a new one.

    Authentication: BearerAuth (JWT).
    Permissions: IsAuthenticated.
    Request body: `ApiKeyCreateSerializer` subset (name, expires_at).
    Success response: success envelope with rotated key data + `api_key`.
    """

    authentication_classes = (JWTAuthentication,)
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ApiKeyCreateSerializer(partial=True),
        responses={
            201: api_key_rotate_success_response,
            400: api_keys_error_response,
            401: api_keys_error_response,
            404: api_keys_error_response,
        },
    )
    def post(self, request: Request, pk: str) -> Response:
        """Revoke the current key (if needed) and return a new key."""
        existing = get_object_or_404(ApiKey, pk=pk, user=request.user)

        if existing.revoked_at is None:
            existing.revoked_at = timezone.now()
            existing.save(update_fields=["revoked_at"])
            rotated_from_revoked = False
        else:
            rotated_from_revoked = True

        payload = {
            "name": request.data.get("name", existing.name),
            "scope": request.data.get("scope", existing.scope),
            "expires_at": request.data.get("expires_at", existing.expires_at),
        }
        serializer = ApiKeyCreateSerializer(
            data=payload,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        new_key = serializer.save()
        out = ApiKeyListSerializer(new_key).data
        out["api_key"] = getattr(new_key, "plaintext_key", None)

        logger.info(
            "api_key.rotated user_id=%s old_key_id=%s new_key_id=%s "
            "rotated_from_revoked=%s scope=%s path=%s method=%s "
            "status_code=%s ip=%s ua=%s",
            getattr(request.user, "id", None),
            getattr(existing, "id", None),
            getattr(new_key, "id", None),
            rotated_from_revoked,
            getattr(new_key, "scope", None),
            getattr(request, "path", ""),
            getattr(request, "method", ""),
            status.HTTP_201_CREATED,
            _client_ip(request),
            request.META.get("HTTP_USER_AGENT"),
        )

        return success_response(
            out,
            message="API key rotated",
            status_code=status.HTTP_201_CREATED,
        )
