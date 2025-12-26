"""Helpers for minting integration JWT access tokens."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from rest_framework_simplejwt.tokens import AccessToken


def mint_integration_access_token(
    client_id: str,
    scope: str,
) -> tuple[str, int]:
    """Mint an integration access token and return it with expiry seconds."""

    lifetime_minutes = int(
        getattr(settings, "INTEGRATION_JWT_ACCESS_MINUTES", 5)
    )
    lifetime = timedelta(minutes=lifetime_minutes)

    token = AccessToken()
    token.set_exp(lifetime=lifetime)
    token["sub"] = client_id
    token["scope"] = scope
    token["iss"] = settings.SIMPLE_JWT["ISSUER"]
    token["aud"] = settings.SIMPLE_JWT["AUDIENCE"]

    return str(token), int(lifetime.total_seconds())
