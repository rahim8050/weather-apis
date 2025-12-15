from __future__ import annotations

from typing import Any, cast

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.http import HttpRequest

UserModel = cast(type[User], get_user_model())


class UsernameOrEmailBackend(ModelBackend):
    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> User | None:
        identifier_obj = kwargs.get("identifier")
        identifier = (
            identifier_obj if isinstance(identifier_obj, str) else None
        )
        login = identifier or username

        if not login or password is None:
            return None

        lookup_field = "email__iexact" if "@" in login else "username__iexact"

        try:
            user = UserModel.objects.get(**{lookup_field: login})
        except UserModel.DoesNotExist:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return cast(User, user)
        return None
