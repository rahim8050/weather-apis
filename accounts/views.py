"""Authentication and user profile API endpoints.

All successful responses are wrapped by
`config.api.responses.success_response`:

    {"status": 0, "message": "<str>", "data": <object|null>, "errors": null}
"""

from __future__ import annotations

from typing import TypeAlias, cast

from django.contrib.auth.models import User
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenRefreshView as SimpleJWTTokenRefresh,
)

from config.api.openapi import (
    error_envelope_serializer,
    success_envelope_serializer,
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

auth_error_response = error_envelope_serializer("AuthErrorResponse")

auth_tokens_schema = inline_serializer(
    name="AuthTokens",
    fields={
        "refresh": serializers.CharField(),
        "access": serializers.CharField(),
    },
)
auth_user_tokens_schema = inline_serializer(
    name="AuthUserTokens",
    fields={
        "user": MeSerializer(),
        "tokens": auth_tokens_schema,
    },
)
auth_success_response = success_envelope_serializer(
    "AuthSuccessResponse",
    data=auth_user_tokens_schema,
)

token_refresh_data_schema = inline_serializer(
    name="TokenRefreshData",
    fields={"access": serializers.CharField()},
)
token_refresh_success_response = success_envelope_serializer(
    "TokenRefreshSuccessResponse",
    data=token_refresh_data_schema,
)

me_success_response = success_envelope_serializer(
    "MeSuccessResponse",
    data=MeSerializer(),
)
password_change_success_response = success_envelope_serializer(
    "PasswordChangeSuccessResponse",
    data=serializers.JSONField(allow_null=True),
)


def _build_tokens(user: User) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


def _as_json_dict(value: object) -> dict[str, JSONValue]:
    return cast(dict[str, JSONValue], value)


@extend_schema(auth=[])
class RegisterView(APIView):
    """Create a new user account.

    Authentication: none.
    Permissions: AllowAny.
    Throttling: scope "register".
    Request body: `RegisterSerializer`.
    Success response: success envelope with `data.user` and `data.tokens`.
    """

    permission_classes = [AllowAny]
    throttle_scope = "register"

    @extend_schema(
        request=RegisterSerializer,
        responses={
            201: auth_success_response,
            400: auth_error_response,
        },
    )
    def post(self, request: Request) -> Response:
        """Register the user and return access/refresh tokens."""
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
    """Authenticate a user and return JWT tokens.

    Authentication: none.
    Permissions: AllowAny.
    Throttling: scope "login".
    Request body: `LoginSerializer`.
    Success response: success envelope with `data.user` and `data.tokens`.
    """

    permission_classes = [AllowAny]
    throttle_scope = "login"

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: auth_success_response,
            400: auth_error_response,
            401: auth_error_response,
        },
    )
    def post(self, request: Request) -> Response:
        """Validate credentials and return access/refresh tokens."""
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
    """Refresh a JWT access token.

    Authentication: none.
    Throttling: scope "token_refresh".
    Request body: SimpleJWT token refresh schema (refresh token).
    Success response: success envelope with `data.access`.
    """

    throttle_scope = "token_refresh"

    @extend_schema(
        request=TokenRefreshSerializer,
        responses={
            200: token_refresh_success_response,
            400: auth_error_response,
            401: auth_error_response,
        },
    )
    def post(
        self,
        request: Request,
        *args: object,
        **kwargs: object,
    ) -> Response:
        """Validate refresh token and return a new access token."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        access = cast(str, serializer.validated_data["access"])
        data: dict[str, JSONValue] = {"access": access}

        return success_response(data, message="Token refreshed")


@extend_schema(auth=cast(list[str], [{"BearerAuth": []}, {"ApiKeyAuth": []}]))
class MeView(APIView):
    """Return the authenticated user's profile.

    Authentication: BearerAuth (JWT) or ApiKeyAuth (X-API-Key).
    Permissions: IsAuthenticated.
    Request body: none.
    Success response: success envelope with `MeSerializer` data.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: me_success_response,
            401: auth_error_response,
        }
    )
    def get(self, request: Request) -> Response:
        """Return the currently authenticated user's profile."""
        user = cast(User, request.user)
        data = _as_json_dict(MeSerializer(user).data)
        return success_response(data, message="User profile")


@extend_schema(auth=cast(list[str], [{"BearerAuth": []}, {"ApiKeyAuth": []}]))
class PasswordChangeView(APIView):
    """Change the authenticated user's password.

    Authentication: BearerAuth (JWT) or ApiKeyAuth (X-API-Key).
    Permissions: IsAuthenticated.
    Request body: `PasswordChangeSerializer`.
    Success response: success envelope with `data = null`.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PasswordChangeSerializer,
        responses={
            200: password_change_success_response,
            400: auth_error_response,
            401: auth_error_response,
        },
    )
    def post(self, request: Request) -> Response:
        """Validate the old password and set the new password."""
        user = cast(User, request.user)
        serializer = PasswordChangeSerializer(
            data=request.data,
            context={"user": user},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(None, message="Password changed")
