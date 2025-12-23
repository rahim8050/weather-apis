# Routes (prefix: /api/v1/auth/):
# - POST register/ -> RegisterView
# - POST login/ -> LoginView
# - POST token/refresh/ -> WrappedTokenRefreshView
# - GET me/ -> MeView
# - POST password/change/ -> PasswordChangeView
# - POST password/reset/ -> PasswordResetRequestView
# - POST password/reset/confirm/ -> PasswordResetConfirmView

from django.urls import path

from .views import (
    LoginView,
    MeView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegisterView,
    WrappedTokenRefreshView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path(
        "token/refresh/",
        WrappedTokenRefreshView.as_view(),
        name="token-refresh",
    ),
    path("me/", MeView.as_view(), name="me"),
    path(
        "password/change/",
        PasswordChangeView.as_view(),
        name="password-change",
    ),
    path(
        "password/reset/",
        PasswordResetRequestView.as_view(),
        name="password-reset",
    ),
    path(
        "password/reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
]
