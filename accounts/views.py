from __future__ import annotations

from typing import TypeAlias, cast

from django.contrib.auth.models import User
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenRefreshView as SimpleJWTTokenRefresh,
)

from config.api.responses import success_response

from .serializers import (
    LoginSerializer,
    MeSerializer,
    PasswordChangeSerializer,
    RegisterSerializer,
)

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def _build_tokens(user: User) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


def _as_json_dict(value: object) -> dict[str, JSONValue]:
    return cast(dict[str, JSONValue], value)


@extend_schema(auth=[])
class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "register"

    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = cast(User, serializer.save())
        user_data = _as_json_dict(MeSerializer(user).data)
        tokens_data = cast(dict[str, JSONValue], _build_tokens(user))

        data: dict[str, JSONValue] = {
            "user": user_data,
            "tokens": tokens_data,
        }

        return success_response(
            data,
            message="Registered successfully",
            status_code=status.HTTP_201_CREATED,
        )


@extend_schema(auth=[])
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "login"

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        user = cast(User, serializer.validated_data["user"])
        user_data = _as_json_dict(MeSerializer(user).data)
        tokens_data = cast(dict[str, JSONValue], _build_tokens(user))

        data: dict[str, JSONValue] = {
            "user": user_data,
            "tokens": tokens_data,
        }

        return success_response(data, message="Login successful")


@extend_schema(auth=[])
class WrappedTokenRefreshView(SimpleJWTTokenRefresh):
    throttle_scope = "token_refresh"

    def post(
        self,
        request: Request,
        *args: object,
        **kwargs: object,
    ) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        access = cast(str, serializer.validated_data["access"])
        data: dict[str, JSONValue] = {"access": access}

        return success_response(data, message="Token refreshed")


@extend_schema(auth=["BearerAuth", "ApiKeyAuth"])
class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = _as_json_dict(MeSerializer(user).data)
        return success_response(data, message="User profile")


@extend_schema(auth=["BearerAuth", "ApiKeyAuth"])
class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        serializer = PasswordChangeSerializer(
            data=request.data,
            context={"user": user},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(None, message="Password changed")
