"""Serializers for integration endpoints.

Note: IntegrationClient secrets are intentionally excluded from all read
serializers. Secrets are only returned once on create/rotate endpoints.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import IntegrationClient


class IntegrationClientSerializer(serializers.ModelSerializer):
    """Read serializer for IntegrationClient (no secret fields)."""

    class Meta:
        model = IntegrationClient
        fields = [
            "id",
            "name",
            "client_id",
            "is_active",
            "rotated_at",
            "previous_expires_at",
            "created_at",
            "updated_at",
        ]


class IntegrationClientCreateSerializer(serializers.ModelSerializer):
    """Create serializer for IntegrationClient (name + optional is_active)."""

    class Meta:
        model = IntegrationClient
        fields = ["name", "is_active"]


class IntegrationClientUpdateSerializer(serializers.ModelSerializer):
    """Update serializer for IntegrationClient (no secret fields)."""

    class Meta:
        model = IntegrationClient
        fields = ["name", "is_active"]


class IntegrationTokenRequestSerializer(serializers.Serializer):
    """Empty request serializer for integration token minting."""
