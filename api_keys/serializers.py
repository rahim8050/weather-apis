from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, cast

from django.utils import timezone
from rest_framework import serializers

from .auth import PREFIX_LENGTH, generate_plaintext_key, hash_api_key
from .models import ApiKey, ApiKeyScope


class ApiKeyWithPlaintext(Protocol):
    plaintext_key: str


class ApiKeyCreateSerializer(serializers.ModelSerializer):
    api_key = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ApiKey
        fields = [
            "id",
            "name",
            "scope",
            "prefix",
            "last4",
            "api_key",
            "expires_at",
        ]
        read_only_fields = ["id", "prefix", "last4", "api_key"]

    def validate_expires_at(self, value: datetime | None) -> datetime | None:
        if value and value <= timezone.now():
            raise serializers.ValidationError(
                "Expiration must be in the future."
            )
        return value

    def get_api_key(self, obj: ApiKey) -> str | None:
        maybe = cast(ApiKeyWithPlaintext, obj)
        return getattr(maybe, "plaintext_key", None)

    def create(self, validated_data: dict[str, Any]) -> ApiKey:
        request = self.context["request"]
        plaintext = generate_plaintext_key()
        api_key = ApiKey.objects.create(
            user=request.user,
            name=validated_data["name"],
            scope=validated_data.get("scope", ApiKeyScope.READ),
            key_hash=hash_api_key(plaintext),
            prefix=plaintext[:PREFIX_LENGTH],
            last4=plaintext[-4:],
            expires_at=validated_data.get("expires_at"),
        )
        cast(ApiKeyWithPlaintext, api_key).plaintext_key = plaintext
        return api_key


class ApiKeyListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApiKey
        fields = [
            "id",
            "name",
            "scope",
            "prefix",
            "last4",
            "created_at",
            "expires_at",
            "revoked_at",
        ]
        read_only_fields = fields
