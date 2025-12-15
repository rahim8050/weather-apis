from __future__ import annotations

import hashlib
import hmac
import secrets

from django.conf import settings
from django.db.models import Q, QuerySet
from django.utils import timezone
from rest_framework.request import Request

from .models import ApiKey

API_KEY_PREFIX = "wk_live_"
PREFIX_LENGTH = 12


def generate_plaintext_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(plaintext_key: str) -> str:
    material = f"{settings.DJANGO_API_KEY_PEPPER}:{plaintext_key}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def get_header_key(request: Request) -> str | None:
    header_value = request.META.get("HTTP_X_API_KEY")
    if header_value:
        return str(header_value)
    return None


def _eligible_keys(prefix: str, last4: str) -> QuerySet[ApiKey]:
    now = timezone.now()
    return ApiKey.objects.filter(
        prefix=prefix,
        last4=last4,
        revoked_at__isnull=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def validate_api_key(raw_key: str) -> ApiKey | None:
    if not raw_key or not raw_key.startswith(API_KEY_PREFIX):
        return None

    prefix = raw_key[:PREFIX_LENGTH]
    last4 = raw_key[-4:]
    candidate_hash = hash_api_key(raw_key)

    for key in _eligible_keys(prefix, last4).iterator():
        if hmac.compare_digest(key.key_hash, candidate_hash):
            return key
    return None
