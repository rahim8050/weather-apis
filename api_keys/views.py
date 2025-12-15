from __future__ import annotations

from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer
from rest_framework.views import APIView

from config.api.responses import success_response

from .models import ApiKey
from .serializers import ApiKeyCreateSerializer, ApiKeyListSerializer


class ApiKeyView(generics.GenericAPIView):
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

    def get(self, request: Request) -> Response:
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(serializer.data, message="API keys")

    def post(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        api_key = serializer.save()
        out = self.get_serializer(api_key).data
        return success_response(
            out,
            message="API key created",
            status_code=status.HTTP_201_CREATED,
        )


class ApiKeyRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request: Request, pk: str) -> Response:
        api_key = get_object_or_404(ApiKey, pk=pk)

        if api_key.user != request.user:
            raise PermissionDenied(
                "You do not have permission to revoke this key."
            )

        if api_key.revoked_at is None:
            api_key.revoked_at = timezone.now()
            api_key.save(update_fields=["revoked_at"])

        return success_response(None, message="API key revoked")
