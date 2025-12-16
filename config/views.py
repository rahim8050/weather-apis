from __future__ import annotations

from django.http import HttpRequest, JsonResponse


def home(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "ok": True,
            "service": "weather-apis",
            "docs": "/api/docs/",
            "redoc": "/api/redoc/",
        }
    )
