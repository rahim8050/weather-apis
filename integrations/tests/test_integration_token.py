from __future__ import annotations

from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.utils.crypto import get_random_string
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.backends import TokenBackend
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken

from integrations.hmac import (
    body_sha256_hex,
    build_canonical_string,
    compute_hmac_signature_hex,
)
from integrations.models import IntegrationClient

User = get_user_model()
TEST_SHARED_SECRET = "test-integration-secret"  # noqa: S105  # nosec B105
TEST_UNKNOWN_SHARED_KEY = "test-unknown-key"
BEARER_TOKEN_TYPE = "Bearer"  # noqa: S105  # nosec B105


def _signature_for_request(
    *,
    shared_secret: str,
    method: str,
    path: str,
    query_string: str,
    timestamp: int,
    nonce: str,
    body: bytes = b"",
) -> str:
    canonical = build_canonical_string(
        method=method,
        path=path,
        query_string=query_string,
        timestamp=timestamp,
        nonce=nonce,
        body_sha256=body_sha256_hex(method=method, body=body),
    )
    return compute_hmac_signature_hex(
        secret=shared_secret,
        canonical_string=canonical,
    )


def _create_api_key(
    client: APIClient, scope: str = "read"
) -> tuple[str, str, str]:
    user = User.objects.create_user(
        username=get_random_string(12),
        password=get_random_string(32),
    )
    access = str(AccessToken.for_user(user))
    resp = client.post(
        "/api/v1/keys/",
        data={"name": "Nextcloud", "scope": scope, "expires_at": None},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code in (200, 201), resp.content
    payload = resp.json()["data"]
    return payload["api_key"], payload["id"], str(user.pk)


def _hmac_headers(
    *,
    client_id: str,
    timestamp: int,
    nonce: str,
    signature: str,
) -> dict[str, str]:
    return {
        "X-Client-Id": client_id,
        "X-Timestamp": str(timestamp),
        "X-Nonce": nonce,
        "X-Signature": signature,
    }


@pytest.mark.django_db
def test_integration_token_mint_success() -> None:
    caches["default"].clear()
    caches["throttle"].clear()

    client = APIClient()
    api_key, key_id, user_id = _create_api_key(client)
    shared_secret = TEST_SHARED_SECRET
    integration_client = IntegrationClient.objects.create(
        name="Nextcloud",
        secret=shared_secret,
    )

    now = 1_700_000_000
    nonce = "nonce-1"
    path = "/api/v1/integration/token/"
    signature = _signature_for_request(
        shared_secret=shared_secret,
        method="POST",
        path=path,
        query_string="",
        timestamp=now,
        nonce=nonce,
        body=b"",
    )

    headers = _hmac_headers(
        client_id=str(integration_client.client_id),
        timestamp=now,
        nonce=nonce,
        signature=signature,
    )
    headers["X-API-Key"] = api_key

    with patch("integrations.hmac.time.time", return_value=now):
        resp = client.post(
            path,
            data=None,
            content_type="application/json",
            headers=headers,
        )

    assert resp.status_code == status.HTTP_200_OK, resp.content
    body = resp.json()
    assert body["status"] == 0
    assert body["data"]["access"]
    assert body["data"]["token_type"] == BEARER_TOKEN_TYPE
    assert body["data"]["expires_in"] == 300
    assert isinstance(key_id, str)

    token = AccessToken(body["data"]["access"])
    assert token["sub"] == user_id
    assert token["user_id"] == user_id
    assert token["scope"] == "read"


@pytest.mark.django_db
def test_integration_token_invalid_signature_denied() -> None:
    caches["default"].clear()
    caches["throttle"].clear()

    client = APIClient()
    api_key, _, _ = _create_api_key(client)
    shared_secret = TEST_SHARED_SECRET
    integration_client = IntegrationClient.objects.create(
        name="Nextcloud",
        secret=shared_secret,
    )

    now = 1_700_000_000
    headers = _hmac_headers(
        client_id=str(integration_client.client_id),
        timestamp=now,
        nonce="nonce-bad",
        signature="deadbeef",
    )
    headers["X-API-Key"] = api_key

    with patch("integrations.hmac.time.time", return_value=now):
        resp = client.post(
            "/api/v1/integration/token/",
            data=None,
            content_type="application/json",
            headers=headers,
        )

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["status"] == 1
    assert resp.json()["errors"]["code"] == "invalid_signature"


@pytest.mark.django_db
def test_integration_token_missing_headers_denied() -> None:
    caches["default"].clear()
    caches["throttle"].clear()

    client = APIClient()
    api_key, _, _ = _create_api_key(client)

    resp = client.post(
        "/api/v1/integration/token/",
        data=None,
        content_type="application/json",
        headers={"X-API-Key": api_key},
    )

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["status"] == 1
    assert resp.json()["errors"]["code"] == "missing_headers"


@pytest.mark.django_db
def test_integration_token_replay_nonce_denied() -> None:
    caches["default"].clear()
    caches["throttle"].clear()

    client = APIClient()
    api_key, _, _ = _create_api_key(client)
    shared_secret = TEST_SHARED_SECRET
    integration_client = IntegrationClient.objects.create(
        name="Nextcloud",
        secret=shared_secret,
    )

    now = 1_700_000_000
    nonce = "nonce-replay"
    signature = _signature_for_request(
        shared_secret=shared_secret,
        method="POST",
        path="/api/v1/integration/token/",
        query_string="",
        timestamp=now,
        nonce=nonce,
        body=b"",
    )
    headers = _hmac_headers(
        client_id=str(integration_client.client_id),
        timestamp=now,
        nonce=nonce,
        signature=signature,
    )
    headers["X-API-Key"] = api_key

    with patch("integrations.hmac.time.time", return_value=now):
        first = client.post(
            "/api/v1/integration/token/",
            data=None,
            content_type="application/json",
            headers=headers,
        )
        second = client.post(
            "/api/v1/integration/token/",
            data=None,
            content_type="application/json",
            headers=headers,
        )

    assert first.status_code == status.HTTP_200_OK, first.content
    assert second.status_code == status.HTTP_403_FORBIDDEN, second.content
    assert second.json()["status"] == 1
    assert second.json()["errors"]["code"] == "nonce_replay"


@pytest.mark.django_db
def test_integration_token_old_timestamp_denied() -> None:
    caches["default"].clear()
    caches["throttle"].clear()

    client = APIClient()
    api_key, _, _ = _create_api_key(client)
    shared_secret = TEST_SHARED_SECRET
    integration_client = IntegrationClient.objects.create(
        name="Nextcloud",
        secret=shared_secret,
    )

    now = 1_700_000_000
    timestamp = now - 301
    signature = _signature_for_request(
        shared_secret=shared_secret,
        method="POST",
        path="/api/v1/integration/token/",
        query_string="",
        timestamp=timestamp,
        nonce="nonce-old",
        body=b"",
    )
    headers = _hmac_headers(
        client_id=str(integration_client.client_id),
        timestamp=timestamp,
        nonce="nonce-old",
        signature=signature,
    )
    headers["X-API-Key"] = api_key

    with patch("integrations.hmac.time.time", return_value=now):
        resp = client.post(
            "/api/v1/integration/token/",
            data=None,
            content_type="application/json",
            headers=headers,
        )

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["status"] == 1
    assert resp.json()["errors"]["code"] == "timestamp_too_old"


@pytest.mark.django_db
def test_integration_token_future_timestamp_denied() -> None:
    caches["default"].clear()
    caches["throttle"].clear()

    client = APIClient()
    api_key, _, _ = _create_api_key(client)
    shared_secret = TEST_SHARED_SECRET
    integration_client = IntegrationClient.objects.create(
        name="Nextcloud",
        secret=shared_secret,
    )

    now = 1_700_000_000
    timestamp = now + 301
    signature = _signature_for_request(
        shared_secret=shared_secret,
        method="POST",
        path="/api/v1/integration/token/",
        query_string="",
        timestamp=timestamp,
        nonce="nonce-future",
        body=b"",
    )
    headers = _hmac_headers(
        client_id=str(integration_client.client_id),
        timestamp=timestamp,
        nonce="nonce-future",
        signature=signature,
    )
    headers["X-API-Key"] = api_key

    with patch("integrations.hmac.time.time", return_value=now):
        resp = client.post(
            "/api/v1/integration/token/",
            data=None,
            content_type="application/json",
            headers=headers,
        )

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["status"] == 1
    assert resp.json()["errors"]["code"] == "timestamp_too_new"


@pytest.mark.django_db
def test_integration_token_unknown_client_denied() -> None:
    caches["default"].clear()
    caches["throttle"].clear()

    client = APIClient()
    api_key, _, _ = _create_api_key(client)

    now = 1_700_000_000
    signature = _signature_for_request(
        shared_secret=TEST_UNKNOWN_SHARED_KEY,
        method="POST",
        path="/api/v1/integration/token/",
        query_string="",
        timestamp=now,
        nonce="nonce-unknown",
        body=b"",
    )
    headers = _hmac_headers(
        client_id="00000000-0000-0000-0000-000000000000",
        timestamp=now,
        nonce="nonce-unknown",
        signature=signature,
    )
    headers["X-API-Key"] = api_key

    with patch("integrations.hmac.time.time", return_value=now):
        resp = client.post(
            "/api/v1/integration/token/",
            data=None,
            content_type="application/json",
            headers=headers,
        )

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["status"] == 1
    assert resp.json()["errors"]["code"] == "unknown_client_id"


@pytest.mark.django_db
def test_integration_token_tampered_body_denied() -> None:
    caches["default"].clear()
    caches["throttle"].clear()

    client = APIClient()
    api_key, _, _ = _create_api_key(client)
    shared_secret = TEST_SHARED_SECRET
    integration_client = IntegrationClient.objects.create(
        name="Nextcloud",
        secret=shared_secret,
    )

    now = 1_700_000_000
    signature = _signature_for_request(
        shared_secret=shared_secret,
        method="POST",
        path="/api/v1/integration/token/",
        query_string="",
        timestamp=now,
        nonce="nonce-body",
        body=b'{"a":1}',
    )
    headers = _hmac_headers(
        client_id=str(integration_client.client_id),
        timestamp=now,
        nonce="nonce-body",
        signature=signature,
    )
    headers["X-API-Key"] = api_key

    with patch("integrations.hmac.time.time", return_value=now):
        resp = client.post(
            "/api/v1/integration/token/",
            data=b'{"a":2}',
            content_type="application/json",
            headers=headers,
        )

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["status"] == 1
    assert resp.json()["errors"]["code"] == "invalid_signature"


@pytest.mark.django_db
def test_integration_token_allows_whoami() -> None:
    caches["default"].clear()
    caches["throttle"].clear()

    client = APIClient()
    api_key, _, user_id = _create_api_key(client)
    shared_secret = TEST_SHARED_SECRET
    integration_client = IntegrationClient.objects.create(
        name="Nextcloud",
        secret=shared_secret,
    )

    now = 1_700_000_000
    nonce = "nonce-whoami"
    signature = _signature_for_request(
        shared_secret=shared_secret,
        method="POST",
        path="/api/v1/integration/token/",
        query_string="",
        timestamp=now,
        nonce=nonce,
        body=b"",
    )
    headers = _hmac_headers(
        client_id=str(integration_client.client_id),
        timestamp=now,
        nonce=nonce,
        signature=signature,
    )
    headers["X-API-Key"] = api_key

    with patch("integrations.hmac.time.time", return_value=now):
        token_resp = client.post(
            "/api/v1/integration/token/",
            data=None,
            content_type="application/json",
            headers=headers,
        )
    assert token_resp.status_code == status.HTTP_200_OK, token_resp.content
    access = token_resp.json()["data"]["access"]

    whoami_resp = client.get(
        "/api/v1/integration/whoami/",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert whoami_resp.status_code == status.HTTP_200_OK, whoami_resp.content
    payload = whoami_resp.json()["data"]
    assert payload["sub"] == user_id
    assert payload["scope"] == "read"


@pytest.mark.django_db
def test_integration_token_accepts_user_id_without_sub() -> None:
    client = APIClient()
    user = User.objects.create_user(
        username=get_random_string(12),
        password=get_random_string(32),
    )
    token = AccessToken()
    token["user_id"] = str(user.pk)
    token["scope"] = "read"
    token["iss"] = settings.SIMPLE_JWT["ISSUER"]
    token["aud"] = settings.SIMPLE_JWT["AUDIENCE"]

    resp = client.get(
        "/api/v1/integration/whoami/",
        HTTP_AUTHORIZATION=f"Bearer {str(token)}",
    )

    assert resp.status_code == status.HTTP_200_OK, resp.content
    payload = resp.json()["data"]
    assert payload["sub"] == str(user.pk)
    assert payload["scope"] == "read"


@pytest.mark.django_db
def test_integration_token_wrong_audience_or_issuer_denied() -> None:
    client = APIClient()

    bad_token = AccessToken()
    bad_token["sub"] = "client-1"
    bad_token["scope"] = "read"
    backend = TokenBackend(
        api_settings.ALGORITHM,
        api_settings.SIGNING_KEY,
        api_settings.VERIFYING_KEY,
        "wrong-audience",
        "wrong-issuer",
        api_settings.JWK_URL,
        api_settings.LEEWAY,
        api_settings.JSON_ENCODER,
    )
    token_str = backend.encode(bad_token.payload)

    resp = client.get(
        "/api/v1/integration/whoami/",
        HTTP_AUTHORIZATION=f"Bearer {token_str}",
    )

    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
