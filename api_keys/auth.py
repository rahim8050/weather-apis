from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Q, QuerySet
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from .models import ApiKey

API_KEY_PREFIX = "wk_live_"
PREFIX_LENGTH = 12


def generate_plaintext_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def _peppered_secret(raw_key: str) -> str:
    return f"{settings.DJANGO_API_KEY_PEPPER}:{raw_key}"


def hash_api_key(plaintext_key: str) -> str:
    return make_password(_peppered_secret(plaintext_key))


def get_header_key(request: Request) -> str | None:
    header_value = request.META.get("HTTP_X_API_KEY")
    if header_value:
        return str(header_value)
    return None


def _eligible_keys(prefix: str, last4: str) -> QuerySet[ApiKey]:
    now = timezone.now()
    active_keys = ApiKey.objects.filter(
        prefix=prefix,
        last4=last4,
        revoked_at__isnull=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    return active_keys.select_related("user")


def validate_api_key(raw_key: str) -> ApiKey | None:
    if not raw_key or not raw_key.startswith(API_KEY_PREFIX):
        return None

    prefix = raw_key[:PREFIX_LENGTH]
    last4 = raw_key[-4:]
    candidate_secret = _peppered_secret(raw_key)

    for key in _eligible_keys(prefix, last4).iterator():
        if check_password(candidate_secret, key.key_hash):
            return key
    return None


class ApiKeyAuthentication(BaseAuthentication):
    www_authenticate_realm = "api"

    def authenticate(
        self, request: Request
    ) -> tuple[AbstractBaseUser, ApiKey] | None:
        raw_key = get_header_key(request)
        if raw_key is None:
            return None

        api_key = validate_api_key(raw_key)
        if api_key is None:
            raise AuthenticationFailed("Invalid or expired API key.")

        if not api_key.user.is_active:
            raise AuthenticationFailed("User inactive or deleted.")

        return api_key.user, api_key

    def authenticate_header(self, request: Request) -> str:
        return "X-API-Key"
