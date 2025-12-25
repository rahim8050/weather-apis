from __future__ import annotations

from typing import TypedDict
from unittest.mock import patch

from django.core.cache import caches
from django.test import SimpleTestCase
from django.test.utils import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from integrations.hmac import (
    body_sha256_hex,
    build_canonical_string,
    canonicalize_query,
    compute_hmac_signature_hex,
)

_TEST_SIGNING_KEY = "test-signing-key"
_KNOWN_GOOD_SIGNING_KEY = "test-shared-secret"
_KNOWN_GOOD_SIGNATURE = (
    "60a6b6568842ac371ba78655d6788e841d61b251dc75157d0dfe4a39f57cc362"
)
_EMPTY_BODY_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)


class _NCHeaders(TypedDict):
    HTTP_X_NC_CLIENT_ID: str
    HTTP_X_NC_TIMESTAMP: str
    HTTP_X_NC_NONCE: str
    HTTP_X_NC_SIGNATURE: str


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


class NextcloudHMACContractTests(SimpleTestCase):
    def test_known_good_vector_matches_docs(self) -> None:
        raw_query = "a=2&b=two%20words&plus=%2B&a=1"
        expected_canonical_query = "a=1&a=2&b=two%20words&plus=%2B"
        self.assertEqual(
            canonicalize_query(raw_query),
            expected_canonical_query,
        )

        canonical = build_canonical_string(
            method="GET",
            path="/api/v1/integrations/nextcloud/ping/",
            query_string=raw_query,
            timestamp=1766666666,
            nonce="550e8400-e29b-41d4-a716-446655440000",
            body_sha256=body_sha256_hex(method="GET", body=b""),
        )
        expected_canonical = "\n".join(
            [
                "GET",
                "/api/v1/integrations/nextcloud/ping/",
                expected_canonical_query,
                "1766666666",
                "550e8400-e29b-41d4-a716-446655440000",
                _EMPTY_BODY_SHA256,
            ]
        )
        self.assertEqual(canonical, expected_canonical)
        self.assertFalse(canonical.endswith("\n"))

        signature = compute_hmac_signature_hex(
            secret=_KNOWN_GOOD_SIGNING_KEY,
            canonical_string=canonical,
        )
        self.assertEqual(signature, _KNOWN_GOOD_SIGNATURE)

    def test_canonical_query_plus_is_decoded_as_space(self) -> None:
        self.assertEqual(canonicalize_query("q=a+b"), "q=a%20b")

    def test_canonical_query_sorted_by_encoded_key_and_value(self) -> None:
        self.assertEqual(
            canonicalize_query("z=1&%C3%A9=2"),
            "%C3%A9=2&z=1",
        )
        self.assertEqual(
            canonicalize_query("k=z&k=%C3%A9"),
            "k=%C3%A9&k=z",
        )


@override_settings(
    NEXTCLOUD_HMAC_ENABLED=True,
    NEXTCLOUD_HMAC_MAX_SKEW_SECONDS=300,
    NEXTCLOUD_HMAC_NONCE_TTL_SECONDS=360,
    NEXTCLOUD_HMAC_CACHE_ALIAS="default",
    NEXTCLOUD_HMAC_CLIENTS={"nc-test-1": _TEST_SIGNING_KEY},
)
class NextcloudHMACTests(APITestCase):
    ping_url = "/api/v1/integrations/nextcloud/ping/"

    def setUp(self) -> None:
        super().setUp()
        caches["default"].clear()
        caches["throttle"].clear()

    def _headers(
        self,
        *,
        client_id: str,
        timestamp: int,
        nonce: str,
        signature: str,
    ) -> _NCHeaders:
        return {
            "HTTP_X_NC_CLIENT_ID": client_id,
            "HTTP_X_NC_TIMESTAMP": str(timestamp),
            "HTTP_X_NC_NONCE": nonce,
            "HTTP_X_NC_SIGNATURE": signature,
        }

    def test_missing_headers_denied(self) -> None:
        resp = self.client.get(self.ping_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.json()["status"], 1)

    def test_unknown_client_id_denied(self) -> None:
        now = 1_700_000_000
        with patch("integrations.hmac.time.time", return_value=now):
            resp = self.client.get(
                self.ping_url,
                **self._headers(
                    client_id="unknown",
                    timestamp=now,
                    nonce="nonce-1",
                    signature="deadbeef",
                ),
            )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.json()["status"], 1)

    def test_invalid_signature_denied(self) -> None:
        now = 1_700_000_000
        with patch("integrations.hmac.time.time", return_value=now):
            resp = self.client.get(
                self.ping_url,
                **self._headers(
                    client_id="nc-test-1",
                    timestamp=now,
                    nonce="nonce-1",
                    signature="not-a-valid-signature",
                ),
            )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.json()["status"], 1)

    def test_valid_signature_returns_client_id(self) -> None:
        now = 1_700_000_000
        nonce = "nonce-1"
        signature = _signature_for_request(
            shared_secret=_TEST_SIGNING_KEY,
            method="GET",
            path=self.ping_url,
            query_string="",
            timestamp=now,
            nonce=nonce,
        )
        with patch("integrations.hmac.time.time", return_value=now):
            resp = self.client.get(
                self.ping_url,
                **self._headers(
                    client_id="nc-test-1",
                    timestamp=now,
                    nonce=nonce,
                    signature=signature,
                ),
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.json()
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["data"]["ok"], True)
        self.assertEqual(body["data"]["client_id"], "nc-test-1")

    def test_valid_signature_accepts_uppercase_hex(self) -> None:
        now = 1_700_000_000
        nonce = "nonce-uc"
        signature = _signature_for_request(
            shared_secret=_TEST_SIGNING_KEY,
            method="GET",
            path=self.ping_url,
            query_string="",
            timestamp=now,
            nonce=nonce,
        ).upper()
        with patch("integrations.hmac.time.time", return_value=now):
            resp = self.client.get(
                self.ping_url,
                **self._headers(
                    client_id="nc-test-1",
                    timestamp=now,
                    nonce=nonce,
                    signature=signature,
                ),
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["data"]["client_id"], "nc-test-1")

    def test_replay_nonce_denied(self) -> None:
        now = 1_700_000_000
        nonce = "nonce-replay"
        signature = _signature_for_request(
            shared_secret=_TEST_SIGNING_KEY,
            method="GET",
            path=self.ping_url,
            query_string="",
            timestamp=now,
            nonce=nonce,
        )
        headers = self._headers(
            client_id="nc-test-1",
            timestamp=now,
            nonce=nonce,
            signature=signature,
        )
        with patch("integrations.hmac.time.time", return_value=now):
            first = self.client.get(self.ping_url, **headers)
            second = self.client.get(self.ping_url, **headers)

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(second.json()["status"], 1)

    def test_old_timestamp_denied(self) -> None:
        now = 1_700_000_000
        timestamp = now - 301
        nonce = "nonce-old"
        signature = _signature_for_request(
            shared_secret=_TEST_SIGNING_KEY,
            method="GET",
            path=self.ping_url,
            query_string="",
            timestamp=timestamp,
            nonce=nonce,
        )
        with patch("integrations.hmac.time.time", return_value=now):
            resp = self.client.get(
                self.ping_url,
                **self._headers(
                    client_id="nc-test-1",
                    timestamp=timestamp,
                    nonce=nonce,
                    signature=signature,
                ),
            )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.json()["status"], 1)

    def test_canonical_query_ordering_validates(self) -> None:
        now = 1_700_000_000
        nonce = "nonce-query"
        signature = _signature_for_request(
            shared_secret=_TEST_SIGNING_KEY,
            method="GET",
            path=self.ping_url,
            query_string="a=1&b=2&b=1",
            timestamp=now,
            nonce=nonce,
        )
        with patch("integrations.hmac.time.time", return_value=now):
            resp = self.client.get(
                f"{self.ping_url}?b=2&a=1&b=1",
                **self._headers(
                    client_id="nc-test-1",
                    timestamp=now,
                    nonce=nonce,
                    signature=signature,
                ),
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["data"]["client_id"], "nc-test-1")
