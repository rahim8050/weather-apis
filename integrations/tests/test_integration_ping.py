from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils.crypto import get_random_string
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

User = get_user_model()


@pytest.mark.django_db
def test_integration_ping_requires_api_key() -> None:
    client = APIClient()
    resp = client.get("/api/v1/integrations/ping/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_integration_ping_requires_api_key_returns_401() -> None:
    client = APIClient()
    resp = client.get("/api/v1/integrations/ping/")
    assert resp.status_code == 401


@override_settings(
    DEBUG=True,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "default-cache",
        },
        "throttle": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "throttle-cache",
        },
    },
)
@pytest.mark.django_db
def test_integration_ping_succeeds_with_api_key() -> None:
    user = User.objects.create_user(
        username="nc", password=get_random_string(32)
    )
    access = str(AccessToken.for_user(user))

    client = APIClient()

    create_resp = client.post(
        "/api/v1/keys/",
        data={"name": "Nextcloud", "scope": "read", "expires_at": None},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert create_resp.status_code in (200, 201), create_resp.content
    payload = create_resp.json()
    api_key = payload["data"]["api_key"]
    assert api_key.startswith("wk_live_")

    ping_resp = client.get(
        "/api/v1/integrations/ping/",
        HTTP_X_API_KEY=api_key,
    )
    assert ping_resp.status_code == 200, ping_resp.content
