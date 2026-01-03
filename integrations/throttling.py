from __future__ import annotations

from django.core.cache import caches
from django.core.cache.backends.base import BaseCache
from django.core.exceptions import ImproperlyConfigured
from rest_framework.request import Request
from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from .hmac import INTEGRATIONS_CLIENT_ID_HEADER, NEXTCLOUD_CLIENT_ID_HEADER


class NextcloudHMACRateThrottle(SimpleRateThrottle):
    scope = "nextcloud_hmac"

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
        client_id = getattr(request, "nc_hmac_client_id", None)
        if not client_id:
            header = request.headers.get(INTEGRATIONS_CLIENT_ID_HEADER)
            if not header:
                header = request.headers.get(NEXTCLOUD_CLIENT_ID_HEADER)
            if header:
                client_id = header

        ident = (
            f"client:{client_id}"
            if client_id
            else f"ip:{self.get_ident(request)}"
        )

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }
