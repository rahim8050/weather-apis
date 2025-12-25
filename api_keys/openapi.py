"""drf-spectacular extensions for API key authentication."""

from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "api_keys.auth.ApiKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(
        self,
        auto_schema: Any,
    ) -> dict[str, object]:
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }
