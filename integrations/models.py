from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from datetime import timedelta

from django.db import models
from django.utils import timezone


class IntegrationClient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, unique=True)
    client_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    secret = models.CharField(max_length=128)
    previous_secret = models.CharField(max_length=128, null=True, blank=True)
    previous_expires_at = models.DateTimeField(null=True, blank=True)
    rotated_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["client_id", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.name

    @staticmethod
    def generate_secret() -> str:
        """Generate a high-entropy secret suitable for HMAC signing."""

        return secrets.token_urlsafe(32)

    def rotate_secret(self, *, overlap_ttl: timedelta) -> str:
        """Rotate the active secret and keep the old one valid temporarily."""

        now = timezone.now()
        self.previous_secret = self.secret
        self.previous_expires_at = now + overlap_ttl
        self.secret = self.generate_secret()
        self.rotated_at = now
        return self.secret

    def candidate_secrets(self) -> Iterator[str]:
        """Yield active secret plus previous secret if still within overlap."""

        yield self.secret
        if (
            self.previous_secret
            and self.previous_expires_at
            and self.previous_expires_at > timezone.now()
        ):
            yield self.previous_secret
