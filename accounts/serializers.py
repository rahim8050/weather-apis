from __future__ import annotations

from typing import Any

from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username__iexact=value).exists():
            msg = _("A user with that username already exists.")
            raise serializers.ValidationError(msg)
        return value

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            msg = _("A user with that email already exists.")
            raise serializers.ValidationError(msg)
        return value

    def validate(self, attrs: dict[str, str]) -> dict[str, str]:
        pw1 = attrs.get("password") or ""
        pw2 = attrs.get("password2") or ""
        if pw1 != pw2:
            raise serializers.ValidationError(
                {"password2": _("Passwords do not match.")}
            )
        password_validation.validate_password(pw1)
        return attrs

    def create(self, validated_data: dict[str, str]) -> User:
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
        )


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs: dict[str, str]) -> dict[str, Any]:
        request = self.context.get("request")
        user = authenticate(
            request=request,
            identifier=attrs.get("identifier"),
            password=attrs.get("password"),
        )
        if user is None:
            raise AuthenticationFailed(_("Invalid credentials."))

        validated: dict[str, Any] = {**attrs, "user": user}
        return validated


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    new_password2 = serializers.CharField(write_only=True)

    def validate(self, attrs: dict[str, str]) -> dict[str, str]:
        user = self.context["user"]
        if not isinstance(user, User):
            raise serializers.ValidationError(_("Invalid user context."))

        if not user.check_password(attrs["old_password"]):
            raise serializers.ValidationError(
                {"old_password": _("Incorrect password.")}
            )

        if attrs["new_password"] != attrs["new_password2"]:
            raise serializers.ValidationError(
                {"new_password2": _("Passwords do not match.")}
            )

        password_validation.validate_password(attrs["new_password"], user)
        return attrs

    def save(self, **kwargs: object) -> User:
        user = self.context["user"]
        if not isinstance(user, User):
            raise serializers.ValidationError("Invalid user context.")
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "date_joined"]
