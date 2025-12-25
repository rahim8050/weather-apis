from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch
from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.utils import timezone
from django.utils.crypto import get_random_string
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from integrations.hmac import (
    body_sha256_hex,
    build_canonical_string,
    compute_hmac_signature_hex,
)
from integrations.models import IntegrationClient


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


def _auth_client(*, access_token: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    return client


@pytest.mark.django_db
def test_integration_client_create_returns_secret_once() -> None:
    user_model = get_user_model()
    admin = user_model.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password=get_random_string(32),
    )
    access = str(AccessToken.for_user(admin))
    client = _auth_client(access_token=access)

    create_resp = client.post(
        "/api/v1/integrations/clients/",
        data={"name": "Nextcloud"},
        format="json",
    )
    assert create_resp.status_code == status.HTTP_201_CREATED, (
        create_resp.content
    )
    body = create_resp.json()
    assert body["status"] == 0

    created = body["data"]
    assert UUID(created["id"])
    assert UUID(created["client_id"])
    assert isinstance(created["client_secret"], str)
    assert created["client_secret"]

    list_resp = client.get("/api/v1/integrations/clients/")
    assert list_resp.status_code == status.HTTP_200_OK, list_resp.content
    listed = list_resp.json()["data"]
    assert isinstance(listed, list)
    assert len(listed) == 1
    assert "client_secret" not in listed[0]
    assert "secret" not in listed[0]
    assert "previous_secret" not in listed[0]

    retrieve_url = f"/api/v1/integrations/clients/{created['id']}/"
    retrieve_resp = client.get(retrieve_url)
    assert retrieve_resp.status_code == status.HTTP_200_OK, (
        retrieve_resp.content
    )
    retrieved = retrieve_resp.json()["data"]
    assert "client_secret" not in retrieved
    assert "secret" not in retrieved
    assert "previous_secret" not in retrieved


@pytest.mark.django_db
def test_integration_client_rotate_secret_supports_overlap_window() -> None:
    caches["default"].clear()
    caches["throttle"].clear()

    user_model = get_user_model()
    admin = user_model.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password=get_random_string(32),
    )
    access = str(AccessToken.for_user(admin))
    client = _auth_client(access_token=access)

    create_resp = client.post(
        "/api/v1/integrations/clients/",
        data={"name": "Nextcloud"},
        format="json",
    )
    assert create_resp.status_code == status.HTTP_201_CREATED, (
        create_resp.content
    )
    created = create_resp.json()["data"]
    integration_client_pk = created["id"]
    client_id = created["client_id"]
    old_secret = created["client_secret"]

    rotate_resp = client.post(
        f"/api/v1/integrations/clients/{integration_client_pk}/rotate-secret/",
    )
    assert rotate_resp.status_code == status.HTTP_200_OK, rotate_resp.content
    rotated = rotate_resp.json()["data"]
    new_secret = rotated["client_secret"]
    assert new_secret != old_secret
    assert rotated["previous_valid_until"] is not None

    ping_url = "/api/v1/integrations/nextcloud/ping/"
    now = 1_700_000_000

    old_sig = _signature_for_request(
        shared_secret=old_secret,
        method="GET",
        path=ping_url,
        query_string="",
        timestamp=now,
        nonce="nonce-old",
    )
    with patch("integrations.hmac.time.time", return_value=now):
        old_ping = client.get(
            ping_url,
            HTTP_X_CLIENT_ID=client_id,
            HTTP_X_NC_TIMESTAMP=str(now),
            HTTP_X_NC_NONCE="nonce-old",
            HTTP_X_NC_SIGNATURE=old_sig,
        )
    assert old_ping.status_code == status.HTTP_200_OK, old_ping.content
    assert old_ping.json()["data"]["client_id"] == client_id

    new_sig = _signature_for_request(
        shared_secret=new_secret,
        method="GET",
        path=ping_url,
        query_string="",
        timestamp=now,
        nonce="nonce-new",
    )
    with patch("integrations.hmac.time.time", return_value=now):
        new_ping = client.get(
            ping_url,
            HTTP_X_CLIENT_ID=client_id,
            HTTP_X_NC_TIMESTAMP=str(now),
            HTTP_X_NC_NONCE="nonce-new",
            HTTP_X_NC_SIGNATURE=new_sig,
        )
    assert new_ping.status_code == status.HTTP_200_OK, new_ping.content
    assert new_ping.json()["data"]["client_id"] == client_id

    IntegrationClient.objects.filter(pk=integration_client_pk).update(
        previous_expires_at=timezone.now() - timedelta(seconds=1)
    )
    expired_sig = _signature_for_request(
        shared_secret=old_secret,
        method="GET",
        path=ping_url,
        query_string="",
        timestamp=now,
        nonce="nonce-expired",
    )
    with patch("integrations.hmac.time.time", return_value=now):
        expired_ping = client.get(
            ping_url,
            HTTP_X_CLIENT_ID=client_id,
            HTTP_X_NC_TIMESTAMP=str(now),
            HTTP_X_NC_NONCE="nonce-expired",
            HTTP_X_NC_SIGNATURE=expired_sig,
        )
    assert expired_ping.status_code == status.HTTP_403_FORBIDDEN
    assert expired_ping.json()["status"] == 1


@pytest.mark.django_db
def test_integration_client_rotate_secret_disabled_client_conflict() -> None:
    user_model = get_user_model()
    admin = user_model.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password=get_random_string(32),
    )
    access = str(AccessToken.for_user(admin))
    client = _auth_client(access_token=access)

    create_resp = client.post(
        "/api/v1/integrations/clients/",
        data={"name": "Nextcloud"},
        format="json",
    )
    assert create_resp.status_code == status.HTTP_201_CREATED, (
        create_resp.content
    )
    created = create_resp.json()["data"]

    disable_resp = client.patch(
        f"/api/v1/integrations/clients/{created['id']}/",
        data={"is_active": False},
        format="json",
    )
    assert disable_resp.status_code == status.HTTP_200_OK, disable_resp.content

    rotate_resp = client.post(
        f"/api/v1/integrations/clients/{created['id']}/rotate-secret/",
    )
    assert rotate_resp.status_code == status.HTTP_409_CONFLICT, (
        rotate_resp.content
    )
    assert rotate_resp.json()["status"] == 1
