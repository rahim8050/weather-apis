"""Integration JWT authentication for service-to-service access tokens."""

from __future__ import annotations

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.models import TokenUser
from rest_framework_simplejwt.tokens import Token


class IntegrationTokenUser(TokenUser):
    """Stateless principal backed by an integration JWT."""

    @property
    def client_id(self) -> str:
        return str(self.token.get("sub", ""))

    @property
    def id(self) -> str:
        return self.client_id

    @property
    def pk(self) -> str:
        return self.client_id

    def __str__(self) -> str:
        return f"IntegrationTokenUser {self.client_id}"


class IntegrationJWTAuthentication(JWTAuthentication):
    """Authenticate integration JWTs that carry `sub` and `scope` claims."""

    def get_user(self, validated_token: Token) -> TokenUser:  # type: ignore[override]
        try:
            validated_token["sub"]
        except KeyError as exc:
            raise InvalidToken("Token missing required subject claim") from exc

        if validated_token.get("scope") is None:
            raise InvalidToken("Token missing required scope claim")

        return IntegrationTokenUser(validated_token)
