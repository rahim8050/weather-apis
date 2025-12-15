from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class ApiKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="api_keys"
    )
    name = models.CharField(max_length=128)
    key_hash = models.CharField(max_length=128, db_index=True)
    prefix = models.CharField(max_length=32)
    last4 = models.CharField(max_length=4)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "revoked_at", "expires_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…{self.last4})"

    @property
    def pepper(self) -> str:
        return settings.DJANGO_API_KEY_PEPPER
