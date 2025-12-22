from __future__ import annotations

# ruff: noqa: S101
from decimal import Decimal
from unittest.mock import patch

from django.test import Client
from rest_framework.exceptions import Throttled
from rest_framework.response import Response

from config.api.exceptions import _to_json_value, custom_exception_handler
from config.api.responses import error_response


def test_error_response_payload() -> None:
    resp = error_response(
        "Bad request",
        errors={"field": ["missing"]},
        status_code=418,
    )
    assert resp.status_code == 418
    assert resp.data["status"] == 1
    assert resp.data["message"] == "Bad request"
    assert resp.data["data"] is None
    assert resp.data["errors"] == {"field": ["missing"]}


def test_custom_exception_handler_returns_500_on_unhandled() -> None:
    with patch("rest_framework.views.exception_handler", return_value=None):
        resp = custom_exception_handler(Exception("boom"), {})
    assert resp.status_code == 500
    assert resp.data["status"] == 1
    assert resp.data["message"] == "Internal server error"


def test_custom_exception_handler_throttled_non_dict_detail() -> None:
    exc = Throttled(wait=12)
    with patch(
        "rest_framework.views.exception_handler",
        return_value=Response("slow down", status=429),
    ):
        resp = custom_exception_handler(exc, {})
    assert resp.status_code == 429
    assert resp.data["message"] == "Too Many Requests"
    assert resp.data["errors"]["detail"] == "slow down"
    assert resp.data["errors"]["wait"] == 12


def test_to_json_value_handles_sequences() -> None:
    payload = ("ok", {"value": Decimal("1.25")})
    assert _to_json_value(payload) == ["ok", {"value": "1.25"}]


def test_home_view_returns_metadata() -> None:
    client = Client()
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["service"] == "weather-apis"
    assert body["docs"] == "/api/docs/"
