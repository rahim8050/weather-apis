from __future__ import annotations

from typing import Any, cast

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from integrations.throttling import NextcloudHMACRateThrottle

_RF: dict[str, Any] = cast(dict[str, Any], settings.REST_FRAMEWORK)
_RF_RATES: dict[str, str] = cast(
    dict[str, str], _RF.get("DEFAULT_THROTTLE_RATES", {})
)


def test_get_rate_returns_none_when_missing() -> None:
    with override_settings(
        REST_FRAMEWORK={
            **_RF,
            "DEFAULT_THROTTLE_RATES": {
                k: v for k, v in _RF_RATES.items() if k != "nextcloud_hmac"
            },
        }
    ):
        api_settings.reload()
        throttle = NextcloudHMACRateThrottle()
        assert throttle.rate is None
    api_settings.reload()


def test_get_rate_rejects_non_string_rate() -> None:
    with override_settings(
        REST_FRAMEWORK={
            **_RF,
            "DEFAULT_THROTTLE_RATES": {
                **_RF_RATES,
                "nextcloud_hmac": 5,
            },
        }
    ):
        api_settings.reload()
        with pytest.raises(ImproperlyConfigured):
            NextcloudHMACRateThrottle()
    api_settings.reload()


def test_get_cache_key_prefers_request_attribute() -> None:
    with override_settings(
        REST_FRAMEWORK={
            **_RF,
            "DEFAULT_THROTTLE_RATES": {
                **_RF_RATES,
                "nextcloud_hmac": "2/min",
            },
        }
    ):
        api_settings.reload()
        throttle = NextcloudHMACRateThrottle()
        request = APIRequestFactory().get("/")
        cast(Any, request).nc_hmac_client_id = "attr-client"

        key = throttle.get_cache_key(request, APIView())

        assert key is not None
        assert "client:attr-client" in key
    api_settings.reload()


def test_get_cache_key_uses_header_then_ip() -> None:
    with override_settings(
        REST_FRAMEWORK={
            **_RF,
            "DEFAULT_THROTTLE_RATES": {
                **_RF_RATES,
                "nextcloud_hmac": "2/min",
            },
        }
    ):
        api_settings.reload()
        throttle = NextcloudHMACRateThrottle()

        header_request = APIRequestFactory().get(
            "/",
            HTTP_X_CLIENT_ID="client-123",
        )
        header_key = throttle.get_cache_key(header_request, APIView())
        assert header_key is not None
        assert "client:client-123" in header_key

        ip_request = APIRequestFactory().get("/")
        ip_key = throttle.get_cache_key(ip_request, APIView())
        assert ip_key is not None
        assert "ip:" in ip_key
    api_settings.reload()
