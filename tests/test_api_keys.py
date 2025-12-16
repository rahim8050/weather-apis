from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.core.cache import caches
from django.test.utils import override_settings
from django.utils import timezone
from django.utils.module_loading import import_string
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory, APITestCase
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from api_keys.auth import validate_api_key
from api_keys.authentication import ApiKeyAuthentication
from api_keys.models import ApiKey
from api_keys.throttling import ApiKeyRateThrottle

_RF: dict[str, Any] = cast(dict[str, Any], settings.REST_FRAMEWORK)
_RF_RATES: dict[str, str] = cast(
    dict[str, str], _RF.get("DEFAULT_THROTTLE_RATES", {})
)


class ApiKeyTests(APITestCase):
    register_url = "/api/v1/auth/register/"
    keys_url = "/api/v1/keys/"

    def setUp(self) -> None:
        super().setUp()
        caches["default"].clear()
        caches["throttle"].clear()

    def _register_and_login(self, username: str = "zoe") -> tuple[str, str]:
        resp = self.client.post(
            self.register_url,
            {
                "username": username,
                "email": f"{username}@example.com",
                "password": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            format="json",
        )
        data = resp.json()["data"]
        return data["tokens"]["access"], data["tokens"]["refresh"]

    def _create_api_key(
        self,
        access: str,
        name: str = "My Key",
    ) -> tuple[str, ApiKey]:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = self.client.post(
            self.keys_url,
            {"name": name, "expires_at": None},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.json()["data"]
        plaintext = data["api_key"]
        api_key = ApiKey.objects.get(id=data["id"])
        return plaintext, api_key

    def test_create_api_key_and_store_only_hash(self) -> None:
        access, _ = self._register_and_login("apiuser")
        plaintext, api_key = self._create_api_key(access, name="My Key")
        self.assertNotEqual(api_key.key_hash, plaintext)
        self.assertTrue(api_key.key_hash.startswith("pbkdf2_"))
        self.assertFalse(hasattr(api_key, "api_key"))

    def test_list_api_keys_never_exposes_plaintext(self) -> None:
        access, _ = self._register_and_login("apilist")
        plaintext, api_key = self._create_api_key(access, name="List Key")
        list_resp = self.client.get(self.keys_url)
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        body = list_resp.json()
        self.assertEqual(body["status"], 0)
        for item in body["data"]:
            self.assertNotIn("api_key", item)
            self.assertNotIn("key_hash", item)
        self.assertNotEqual(api_key.key_hash, plaintext)

    def test_revoke_api_key_and_validate_helper(self) -> None:
        access, _ = self._register_and_login("apirevoke")
        plaintext, api_key = self._create_api_key(access, name="Revoke Me")
        revoke_resp = self.client.delete(f"{self.keys_url}{api_key.id}/")
        self.assertEqual(revoke_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(revoke_resp.json()["status"], 0)

        api_key.refresh_from_db()
        self.assertIsNotNone(api_key.revoked_at)
        self.assertIsNone(validate_api_key(plaintext))

    def test_cannot_revoke_other_users_key(self) -> None:
        access1, _ = self._register_and_login("owner")
        _, api_key = self._create_api_key(access1, name="Owner Key")

        access2, _ = self._register_and_login("intruder")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access2}")
        resp = self.client.delete(f"{self.keys_url}{api_key.id}/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.json()["status"], 1)

    def test_api_key_header_authenticates_requests(self) -> None:
        access, _ = self._register_and_login("headerauth")
        plaintext, api_key = self._create_api_key(access, name="Header Key")

        class ProtectedView(APIView):
            authentication_classes = (ApiKeyAuthentication,)
            permission_classes = (AllowAny,)

            def get(self, request: Request) -> Response:  # type: ignore[override]
                return Response({"ok": True})

        factory = APIRequestFactory()
        resp = ProtectedView.as_view()(
            factory.get("/protected", HTTP_X_API_KEY=plaintext)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["ok"], True)

    def test_missing_or_invalid_api_key_denied(self) -> None:
        resp = self.client.get(self.keys_url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

        resp_invalid = self.client.get(
            self.keys_url,
            HTTP_X_API_KEY="wk_live_notreal",
        )
        self.assertEqual(
            resp_invalid.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_revoked_or_expired_key_denied(self) -> None:
        access, _ = self._register_and_login("expired")
        plaintext, api_key = self._create_api_key(access, name="Short Lived")

        revoke_resp = self.client.delete(f"{self.keys_url}{api_key.id}/")
        self.assertEqual(revoke_resp.status_code, status.HTTP_200_OK)

        self.client.credentials()
        resp = self.client.get(self.keys_url, HTTP_X_API_KEY=plaintext)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

        api_key.refresh_from_db()
        api_key.revoked_at = None
        api_key.expires_at = timezone.now() - timedelta(minutes=1)
        api_key.save(update_fields=["revoked_at", "expires_at"])

        expired_resp = self.client.get(
            self.keys_url,
            HTTP_X_API_KEY=plaintext,
        )
        self.assertEqual(
            expired_resp.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_api_key_auth_cannot_manage_keys(self) -> None:
        access, _ = self._register_and_login("onlyjwt")
        plaintext, api_key = self._create_api_key(access, name="My Key")

        self.client.credentials()
        list_resp = self.client.get(self.keys_url, HTTP_X_API_KEY=plaintext)
        self.assertEqual(list_resp.status_code, status.HTTP_401_UNAUTHORIZED)

        post_resp = self.client.post(
            self.keys_url,
            {"name": "Blocked"},
            format="json",
            HTTP_X_API_KEY=plaintext,
        )
        self.assertEqual(post_resp.status_code, status.HTTP_401_UNAUTHORIZED)

        delete_resp = self.client.delete(
            f"{self.keys_url}{api_key.id}/",
            HTTP_X_API_KEY=plaintext,
        )
        self.assertEqual(delete_resp.status_code, status.HTTP_401_UNAUTHORIZED)

        rotate_resp = self.client.post(
            f"{self.keys_url}{api_key.id}/rotate/",
            HTTP_X_API_KEY=plaintext,
        )
        self.assertEqual(rotate_resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rotate_api_key_returns_new_and_revokes_old(self) -> None:
        access, _ = self._register_and_login("rotate")
        old_plaintext, old_key = self._create_api_key(access, name="Old Key")

        rotate_resp = self.client.post(
            f"{self.keys_url}{old_key.id}/rotate/",
            {"name": "Rotated Key"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        self.assertEqual(rotate_resp.status_code, status.HTTP_201_CREATED)
        body = rotate_resp.json()
        self.assertEqual(body["status"], 0)
        data = cast(dict[str, Any], body["data"])
        new_plaintext = data["api_key"]
        new_id = data["id"]

        old_key.refresh_from_db()
        self.assertIsNotNone(old_key.revoked_at)
        self.assertIsNone(validate_api_key(old_plaintext))
        self.assertIsNotNone(validate_api_key(new_plaintext))
        self.assertNotEqual(str(old_key.id), new_id)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        list_resp = self.client.get(self.keys_url)
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        for item in list_resp.json()["data"]:
            self.assertNotIn("api_key", item)

        self.client.credentials()
        old_auth_resp = self.client.get(
            self.keys_url,
            HTTP_X_API_KEY=old_plaintext,
        )
        self.assertEqual(
            old_auth_resp.status_code, status.HTTP_401_UNAUTHORIZED
        )

    @override_settings(
        REST_FRAMEWORK={
            **_RF,
            "DEFAULT_THROTTLE_CLASSES": (
                "api_keys.throttling.ApiKeyRateThrottle",
            ),
            "DEFAULT_THROTTLE_RATES": {
                **_RF_RATES,
                "api_key": "2/min",
            },
        }
    )
    def test_per_key_throttling_is_isolated(self) -> None:
        api_settings.reload()
        ApiKeyRateThrottle = import_string(
            "api_keys.throttling.ApiKeyRateThrottle"
        )

        class ThrottledView(APIView):
            authentication_classes = (ApiKeyAuthentication,)
            permission_classes = (AllowAny,)
            throttle_classes = (ApiKeyRateThrottle,)

            def get(self, request: Request) -> Response:  # type: ignore[override]
                return Response({"ok": True})

        access, _ = self._register_and_login("ratelimit")
        key1, _ = self._create_api_key(access, name="Key One")
        key2, _ = self._create_api_key(access, name="Key Two")

        factory = APIRequestFactory()
        view = ThrottledView.as_view()

        for _ in range(2):
            ok_resp = view(factory.get("/t", HTTP_X_API_KEY=key1))
            self.assertEqual(ok_resp.status_code, status.HTTP_200_OK)

        blocked = view(factory.get("/t", HTTP_X_API_KEY=key1))
        self.assertEqual(
            blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS
        )

        other_key_resp = view(factory.get("/t", HTTP_X_API_KEY=key2))
        self.assertEqual(other_key_resp.status_code, status.HTTP_200_OK)

    def test_throttle_uses_throttle_cache_alias(self) -> None:
        throttle = ApiKeyRateThrottle()
        self.assertIs(throttle.cache, caches["throttle"])

    def test_throttle_ignores_header_without_api_key_auth(self) -> None:
        access, _ = self._register_and_login("jwtthrottle")

        class JwtThrottleView(APIView):
            authentication_classes = (JWTAuthentication,)
            permission_classes = (AllowAny,)
            throttle_classes = (ApiKeyRateThrottle,)

            def get(self, request: Request) -> Response:  # type: ignore[override]
                return Response({"ok": True})

        view = JwtThrottleView.as_view()
        factory = APIRequestFactory()

        for _ in range(3):
            resp = view(
                factory.get(
                    "/t",
                    HTTP_AUTHORIZATION=f"Bearer {access}",
                    HTTP_X_API_KEY="wk_live_fake",
                )
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
