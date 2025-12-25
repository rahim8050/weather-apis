"""Nextcloud instance-level HMAC request signing helpers.

This module implements request-integrity verification and replay protection for
Nextcloud -> DRF calls using a shared-secret HMAC contract.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote

from django.conf import settings
from django.core.cache import caches
from rest_framework.request import Request

NEXTCLOUD_CLIENT_ID_HEADER = "X-NC-CLIENT-ID"
NEXTCLOUD_TIMESTAMP_HEADER = "X-NC-TIMESTAMP"
NEXTCLOUD_NONCE_HEADER = "X-NC-NONCE"
NEXTCLOUD_SIGNATURE_HEADER = "X-NC-SIGNATURE"
INTEGRATIONS_CLIENT_ID_HEADER = "X-Client-Id"

_RFC3986_SAFE = "-_.~"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NextcloudHMACHeaders:
    """Parsed Nextcloud signature headers."""

    client_id: str
    timestamp: int
    nonce: str
    signature: str


class NextcloudHMACVerificationError(Exception):
    """Raised when a request fails Nextcloud HMAC verification."""


def canonicalize_query(query_string: str) -> str:
    """Parse, sort, and re-encode a query string; preserve duplicates."""

    if not query_string:
        return ""

    pairs = parse_qsl(
        query_string,
        keep_blank_values=True,
        strict_parsing=False,
        separator="&",
    )
    encoded_pairs = [
        (quote(k, safe=_RFC3986_SAFE), quote(v, safe=_RFC3986_SAFE))
        for k, v in pairs
    ]
    encoded_pairs.sort(key=lambda item: (item[0], item[1]))
    return "&".join(f"{k}={v}" for k, v in encoded_pairs)


def body_sha256_hex(*, method: str, body: bytes) -> str:
    """Compute sha256 hex of raw request body (empty bytes for GET)."""

    if method.upper() == "GET":
        body = b""
    return hashlib.sha256(body).hexdigest()


def build_canonical_string(
    *,
    method: str,
    path: str,
    query_string: str,
    timestamp: int,
    nonce: str,
    body_sha256: str,
) -> str:
    """Build the newline-separated canonical string for verification."""

    return "\n".join(
        [
            method.upper(),
            path,
            canonicalize_query(query_string),
            str(timestamp),
            nonce,
            body_sha256,
        ]
    )


def compute_hmac_signature_hex(*, secret: str, canonical_string: str) -> str:
    """Compute the expected hex HMAC-SHA256 signature."""

    digest = hmac.new(
        secret.encode("utf-8"),
        canonical_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def _get_required_headers(request: Request) -> NextcloudHMACHeaders:
    client_id = request.headers.get(NEXTCLOUD_CLIENT_ID_HEADER)
    if not client_id:
        client_id = request.headers.get(INTEGRATIONS_CLIENT_ID_HEADER)
    timestamp_raw = request.headers.get(NEXTCLOUD_TIMESTAMP_HEADER)
    nonce = request.headers.get(NEXTCLOUD_NONCE_HEADER)
    signature = request.headers.get(NEXTCLOUD_SIGNATURE_HEADER)

    if not client_id or not timestamp_raw or not nonce or not signature:
        raise NextcloudHMACVerificationError("Missing Nextcloud HMAC headers")

    try:
        timestamp = int(timestamp_raw)
    except ValueError as exc:
        raise NextcloudHMACVerificationError(
            "Invalid Nextcloud timestamp header"
        ) from exc

    return NextcloudHMACHeaders(
        client_id=client_id,
        timestamp=timestamp,
        nonce=nonce,
        signature=signature.lower(),
    )


def verify_nextcloud_hmac_request(request: Request) -> str:
    """Verify request signature + replay protection; return `client_id`.

    Raises `NextcloudHMACVerificationError` on any verification failure.
    """

    if not getattr(settings, "NEXTCLOUD_HMAC_ENABLED", True):
        client_id = request.headers.get(NEXTCLOUD_CLIENT_ID_HEADER, "")
        return client_id

    headers = _get_required_headers(request)

    secrets_to_try: list[str] = []
    matched_integration_client_previous_secret = False

    integration_client_id: uuid.UUID | None = None
    try:
        integration_client_id = uuid.UUID(headers.client_id)
    except ValueError:
        integration_client_id = None

    if integration_client_id is not None:
        # Lazy import: avoid importing models at module import time.
        from .models import IntegrationClient

        integration_client = IntegrationClient.objects.filter(
            client_id=integration_client_id
        ).first()
        if integration_client is not None:
            if not integration_client.is_active:
                raise NextcloudHMACVerificationError(
                    "Integration client is disabled"
                )
            secrets_to_try = list(integration_client.candidate_secrets())

    if not secrets_to_try:
        clients: dict[str, str] = getattr(
            settings, "NEXTCLOUD_HMAC_CLIENTS", {}
        )
        secret = clients.get(headers.client_id)
        if secret is None:
            raise NextcloudHMACVerificationError("Unknown Nextcloud client_id")
        secrets_to_try = [secret]

    now = int(time.time())
    max_skew = int(getattr(settings, "NEXTCLOUD_HMAC_MAX_SKEW_SECONDS", 300))
    if abs(now - headers.timestamp) > max_skew:
        raise NextcloudHMACVerificationError(
            "Nextcloud timestamp outside skew"
        )

    method = request.method
    if not method:
        raise NextcloudHMACVerificationError("Invalid request method")

    canonical = build_canonical_string(
        method=method,
        path=request.path,
        query_string=request.META.get("QUERY_STRING", ""),
        timestamp=headers.timestamp,
        nonce=headers.nonce,
        body_sha256=body_sha256_hex(
            method=method,
            body=request.body,
        ),
    )
    expected_sig = compute_hmac_signature_hex(
        secret=secrets_to_try[0],
        canonical_string=canonical,
    )
    if hmac.compare_digest(headers.signature, expected_sig):
        matched_integration_client_previous_secret = False
    else:
        matched = False
        for idx, candidate_secret in enumerate(secrets_to_try[1:], start=1):
            candidate_sig = compute_hmac_signature_hex(
                secret=candidate_secret,
                canonical_string=canonical,
            )
            if hmac.compare_digest(headers.signature, candidate_sig):
                matched = True
                matched_integration_client_previous_secret = idx > 0
                break
        if not matched:
            raise NextcloudHMACVerificationError("Invalid Nextcloud signature")

    if matched_integration_client_previous_secret:
        logger.info(
            "nextcloud_hmac.verified_with_previous_secret "
            "client_id=%s path=%s",
            headers.client_id,
            request.path,
        )

    cache_alias = str(
        getattr(settings, "NEXTCLOUD_HMAC_CACHE_ALIAS", "default")
    )
    nonce_ttl = int(getattr(settings, "NEXTCLOUD_HMAC_NONCE_TTL_SECONDS", 360))
    cache = caches[cache_alias]
    cache_key = f"nc_hmac:{headers.client_id}:{headers.nonce}"
    if not cache.add(cache_key, 1, timeout=nonce_ttl):
        raise NextcloudHMACVerificationError("Nextcloud nonce replay detected")

    return headers.client_id
