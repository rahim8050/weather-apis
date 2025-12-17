"""Project-level non-DRF views.

This module contains the root landing endpoint used for quick service checks
and links to the interactive API documentation endpoints.
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse


def home(request: HttpRequest) -> JsonResponse:
    """Return basic service metadata and documentation links."""
    return JsonResponse(
        {
            "ok": True,
            "service": "weather-apis",
            "docs": "/api/docs/",
            "redoc": "/api/redoc/",
        }
    )
