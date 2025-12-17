# Routes (prefix: /api/v1/keys/):
# - GET / -> ApiKeyView (list)
# - POST / -> ApiKeyView (create)
# - DELETE /<uuid:pk>/ -> ApiKeyRevokeView
# - POST /<uuid:pk>/rotate/ -> ApiKeyRotateView

from django.urls import path

from .views import ApiKeyRevokeView, ApiKeyRotateView, ApiKeyView

urlpatterns = [
    path("", ApiKeyView.as_view(), name="api-key-list-create"),
    path("<uuid:pk>/", ApiKeyRevokeView.as_view(), name="api-key-revoke"),
    path(
        "<uuid:pk>/rotate/",
        ApiKeyRotateView.as_view(),
        name="api-key-rotate",
    ),
]
