from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.cache import caches
from django.core.cache.backends.base import BaseCache
from django.core.exceptions import ImproperlyConfigured
from rest_framework.request import Request
from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle

from api_keys.models import ApiKey

if TYPE_CHECKING:
    from rest_framework.views import APIView


class ApiKeyRateThrottle(SimpleRateThrottle):
    scope = "api_key"

    def __init__(self) -> None:
        super().__init__()
        self.cache: BaseCache = caches["throttle"]

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
        auth = getattr(request, "auth", None)
        if not isinstance(auth, ApiKey):
            return None

        return self.cache_format % {
            "scope": self.scope,
            "ident": str(auth.id),
        }
