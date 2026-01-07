from __future__ import annotations

import base64
import json
from typing import Any, TypedDict, cast
from unittest.mock import patch

from django.conf import settings
from django.core.cache import caches
from django.test import SimpleTestCase
from django.test.utils import override_settings
from rest_framework import status
from rest_framework.settings import api_settings
from rest_framework.test import APITestCase

from integrations.hmac import (
    body_sha256_hex,
    build_canonical_string,
    canonicalize_query,
    compute_hmac_signature_hex,
)

_TEST_SIGNING_KEY = b"test-signing-key"
_TEST_SIGNING_KEY_B64 = base64.b64encode(_TEST_SIGNING_KEY).decode("ascii")
_TEST_CLIENTS_JSON = json.dumps({"nc-test-1": _TEST_SIGNING_KEY_B64})
_KNOWN_GOOD_SIGNING_KEY = b"test-shared-secret"
_KNOWN_GOOD_SIGNATURE = (
    "60a6b6568842ac371ba78655d6788e841d61b251dc75157d0dfe4a39f57cc362"
)
_EMPTY_BODY_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)

_RF: dict[str, Any] = cast(dict[str, Any], settings.REST_FRAMEWORK)
_RF_RATES: dict[str, str] = cast(
    dict[str, str], _RF.get("DEFAULT_THROTTLE_RATES", {})
)


class _NCHeaders(TypedDict):
    HTTP_X_NC_CLIENT_ID: str
    HTTP_X_NC_TIMESTAMP: str
    HTTP_X_NC_NONCE: str
    HTTP_X_NC_SIGNATURE: str


def _signature_for_request(
    *,
    shared_secret: bytes,
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
    INTEGRATION_HMAC_CLIENTS_JSON=_TEST_CLIENTS_JSON,
    INTEGRATION_LEGACY_CONFIG_ALLOWED=True,
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
        self.assertEqual(resp.json()["errors"]["code"], "missing_headers")

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
        self.assertEqual(resp.json()["errors"]["code"], "unknown_client")

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
        self.assertEqual(resp.json()["errors"]["code"], "sig_mismatch")

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
        self.assertEqual(second.json()["errors"]["code"], "replay")

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
        self.assertEqual(resp.json()["errors"]["code"], "skew")

    def test_future_timestamp_denied(self) -> None:
        now = 1_700_000_000
        timestamp = now + 301
        nonce = "nonce-future"
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
        self.assertEqual(resp.json()["errors"]["code"], "skew")

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

    def test_path_mismatch_returns_code(self) -> None:
        now = 1_700_000_000
        nonce = "nonce-path"
        signature = _signature_for_request(
            shared_secret=_TEST_SIGNING_KEY,
            method="GET",
            path="/api/v1/integrations/nextcloud/ping",
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
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.json()["errors"]["code"], "path_mismatch")

    def test_method_mismatch_returns_code(self) -> None:
        now = 1_700_000_000
        nonce = "nonce-method"
        signature = _signature_for_request(
            shared_secret=_TEST_SIGNING_KEY,
            method="HEAD",
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
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.json()["errors"]["code"], "method_mismatch")

    @override_settings(
        REST_FRAMEWORK={
            **_RF,
            "DEFAULT_THROTTLE_RATES": {
                **_RF_RATES,
                "nextcloud_hmac": "1/min",
            },
        }
    )
    def test_rate_limit_returns_retry_after(self) -> None:
        api_settings.reload()

        now = 1_700_000_000
        first_nonce = "nonce-throttle-1"
        first_signature = _signature_for_request(
            shared_secret=_TEST_SIGNING_KEY,
            method="GET",
            path=self.ping_url,
            query_string="",
            timestamp=now,
            nonce=first_nonce,
        )
        first_headers = self._headers(
            client_id="nc-test-1",
            timestamp=now,
            nonce=first_nonce,
            signature=first_signature,
        )
        with patch("integrations.hmac.time.time", return_value=now):
            first = self.client.get(self.ping_url, **first_headers)
            second_nonce = "nonce-throttle-2"
            second_signature = _signature_for_request(
                shared_secret=_TEST_SIGNING_KEY,
                method="GET",
                path=self.ping_url,
                query_string="",
                timestamp=now,
                nonce=second_nonce,
            )
            second_headers = self._headers(
                client_id="nc-test-1",
                timestamp=now,
                nonce=second_nonce,
                signature=second_signature,
            )
            second = self.client.get(self.ping_url, **second_headers)

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        payload = second.json()
        self.assertEqual(payload["status"], 1)
        self.assertEqual(payload["message"], "Too Many Requests")
        self.assertIn("wait", payload["errors"])
        retry_after = second.get("Retry-After")
        self.assertIsNotNone(retry_after)


@override_settings(
    NEXTCLOUD_HMAC_ENABLED=True,
    NEXTCLOUD_HMAC_MAX_SKEW_SECONDS=300,
    NEXTCLOUD_HMAC_NONCE_TTL_SECONDS=360,
    NEXTCLOUD_HMAC_CACHE_ALIAS="default",
    INTEGRATION_HMAC_CLIENTS_JSON='{"nc-test-1":"not-base64"}',
    INTEGRATION_LEGACY_CONFIG_ALLOWED=True,
)
class NextcloudHMACConfigErrorTests(APITestCase):
    ping_url = "/api/v1/integrations/nextcloud/ping/"

    def test_bad_base64_denied(self) -> None:
        now = 1_700_000_000
        nonce = "nonce-b64"
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
                HTTP_X_NC_CLIENT_ID="nc-test-1",
                HTTP_X_NC_TIMESTAMP=str(now),
                HTTP_X_NC_NONCE=nonce,
                HTTP_X_NC_SIGNATURE=signature,
            )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.json()["errors"]["code"], "bad_base64")
