from django.urls import path

from .views import ApiKeyRevokeView, ApiKeyView

urlpatterns = [
    path("", ApiKeyView.as_view(), name="api-key-list-create"),
    path("<uuid:pk>/", ApiKeyRevokeView.as_view(), name="api-key-revoke"),
]
