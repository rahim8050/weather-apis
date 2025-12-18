from __future__ import annotations

from typing import cast

from django.db.models import QuerySet
from rest_framework.permissions import IsAuthenticated
from rest_framework.serializers import BaseSerializer
from rest_framework.viewsets import ModelViewSet

from .models import Farm
from .permissions import IsFarmOwner
from .serializers import FarmSerializer


class FarmViewSet(ModelViewSet):
    serializer_class = FarmSerializer
    permission_classes = [IsAuthenticated, IsFarmOwner]

    def get_queryset(self) -> QuerySet[Farm]:
        # Owner-only visibility
        user_id = getattr(self.request.user, "id", None)
        if user_id is None:
            return Farm.objects.none()
        return Farm.objects.filter(owner_id=cast(int, user_id)).order_by(
            "-created_at"
        )

    def perform_create(self, serializer: BaseSerializer[Farm]) -> None:
        # Prevents clients from spoofing owner
        serializer.save(owner=self.request.user)
