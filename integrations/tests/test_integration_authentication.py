from __future__ import annotations

import pytest
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import AccessToken

from integrations.authentication import (
    IntegrationJWTAuthentication,
    IntegrationTokenUser,
)


def test_integration_jwt_auth_rejects_missing_subject() -> None:
    token = AccessToken()
    token["scope"] = "read"

    auth = IntegrationJWTAuthentication()
    with pytest.raises(InvalidToken):
        auth.get_user(token)


def test_integration_jwt_auth_rejects_missing_scope() -> None:
    token = AccessToken()
    token["sub"] = "client-1"

    auth = IntegrationJWTAuthentication()
    with pytest.raises(InvalidToken):
        auth.get_user(token)


def test_integration_token_user_properties() -> None:
    token = AccessToken()
    token["sub"] = "client-42"
    token["scope"] = "read"

    auth = IntegrationJWTAuthentication()
    user = auth.get_user(token)

    assert isinstance(user, IntegrationTokenUser)
    assert user.client_id == "client-42"
    assert user.id == "client-42"
    assert user.pk == "client-42"
    assert str(user) == "IntegrationTokenUser client-42"
