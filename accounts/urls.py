# Routes (prefix: /api/v1/auth/):
# - POST register/ -> RegisterView
# - POST login/ -> LoginView
# - POST token/refresh/ -> WrappedTokenRefreshView
# - GET me/ -> MeView
# - POST password/change/ -> PasswordChangeView

from django.urls import path

from .views import (
    LoginView,
    MeView,
    PasswordChangeView,
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
]
