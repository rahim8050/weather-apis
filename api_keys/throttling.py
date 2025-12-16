from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from rest_framework.request import Request
from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle

if TYPE_CHECKING:
    from rest_framework.views import APIView


class ApiKeyRateThrottle(SimpleRateThrottle):
    scope = "api_key"
    cache = cache  # use default cache (works in tests + prod)

    def get_rate(self) -> str | None:
        rate: object = api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)
        if rate is None:
            return None
        if not isinstance(rate, str):
            raise ImproperlyConfigured(
                "Throttle rate must be a string like '2/min'."
            )
        return rate

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        raw_key = request.META.get("HTTP_X_API_KEY")
        if not raw_key:
            return None

        pepper = getattr(settings, "DJANGO_API_KEY_PEPPER", "")
        ident = hashlib.sha256(f"{pepper}:{raw_key}".encode()).hexdigest()

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }
