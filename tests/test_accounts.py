from __future__ import annotations

import secrets
from typing import Final, Protocol, TypeAlias, cast

from rest_framework import status
from rest_framework.test import APITestCase

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class JsonClientResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JSONValue]: ...


class AccountsTests(APITestCase):
    REGISTER_URL: Final[str] = "/api/v1/auth/register/"
    LOGIN_URL: Final[str] = "/api/v1/auth/login/"
    REFRESH_URL: Final[str] = "/api/v1/auth/token/refresh/"
    ME_URL: Final[str] = "/api/v1/auth/me/"
    PW_CHANGE_URL: Final[str] = "/api/v1/auth/password/change/"

    def _pw(self) -> str:
        # Validator-friendly and non-static.
        # (avoids Bandit hardcoded password hits)
        return f"{secrets.token_urlsafe(16)}Aa1!"

    def _as_dict(
        self, value: JSONValue | None, label: str
    ) -> dict[str, JSONValue]:
        if not isinstance(value, dict):
            self.fail(f"Expected dict for {label}")
        return value

    def _as_str(self, value: JSONValue | None, label: str) -> str:
        if not isinstance(value, str):
            self.fail(f"Expected str for {label}")
        return value

    def _register(
        self,
        username: str = "alice",
        email: str = "alice@example.com",
        password: str | None = None,
    ) -> JsonClientResponse:
        pw = password or self._pw()
        payload = {
            "username": username,
            "email": email,
            "password": pw,
            "password2": pw,
        }
        return cast(
            JsonClientResponse,
            self.client.post(self.REGISTER_URL, payload, format="json"),
        )

    def _login(self, identifier: str, password: str) -> JsonClientResponse:
        return cast(
            JsonClientResponse,
            self.client.post(
                self.LOGIN_URL,
                {"identifier": identifier, "password": password},
                format="json",
            ),
        )

    def test_register_success_returns_tokens(self) -> None:
        resp = self._register()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        body = resp.json()
        self.assertEqual(body.get("status"), 0)

        data = self._as_dict(body.get("data"), "data")
        self.assertIn("tokens", data)
        self.assertIn("user", data)

    def test_register_password_mismatch_returns_error(self) -> None:
        pw1 = self._pw()
        pw2 = self._pw()

        payload = {
            "username": "bob",
            "email": "bob@example.com",
            "password": pw1,
            "password2": pw2,
        }
        resp = cast(
            JsonClientResponse,
            self.client.post(self.REGISTER_URL, payload, format="json"),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        body = resp.json()
        self.assertEqual(body.get("status"), 1)
        self.assertIsNotNone(body.get("errors"))

    def test_register_duplicate_username_or_email_case_insensitive(
        self,
    ) -> None:
        pw = self._pw()
        self._register(
            username="charlie",
            email="charlie@example.com",
            password=pw,
        )

        resp = self._register(
            username="CHARLIE",
            email="CHARLIE@example.com",
            password=pw,
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json().get("status"), 1)

    def test_login_with_username_identifier(self) -> None:
        pw = self._pw()
        self._register(username="dana", email="dana@example.com", password=pw)

        resp = self._login("dana", pw)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        body = resp.json()
        self.assertEqual(body.get("status"), 0)

        data = self._as_dict(body.get("data"), "data")
        tokens = self._as_dict(data.get("tokens"), "data.tokens")
        self.assertIn("access", tokens)

    def test_login_with_email_identifier_case_insensitive(self) -> None:
        pw = self._pw()
        self._register(username="eric", email="eric@example.com", password=pw)

        resp = self._login("ERIC@EXAMPLE.COM", pw)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json().get("status"), 0)

    def test_login_wrong_password_generic_error(self) -> None:
        real_pw = self._pw()
        wrong_pw = f"{real_pw}x"

        self._register(
            username="frank",
            email="frank@example.com",
            password=real_pw,
        )

        resp = self._login("frank", wrong_pw)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.json().get("status"), 1)

    def test_token_refresh_returns_new_access_token(self) -> None:
        resp = self._register(username="gina", email="gina@example.com")

        body = resp.json()
        data = self._as_dict(body.get("data"), "data")
        tokens = self._as_dict(data.get("tokens"), "data.tokens")
        refresh = self._as_str(tokens.get("refresh"), "data.tokens.refresh")

        refresh_resp = cast(
            JsonClientResponse,
            self.client.post(
                self.REFRESH_URL,
                {"refresh": refresh},
                format="json",
            ),
        )
        self.assertEqual(refresh_resp.status_code, status.HTTP_200_OK)

        out = refresh_resp.json()
        self.assertEqual(out.get("status"), 0)

        out_data = self._as_dict(out.get("data"), "data")
        self.assertIn("access", out_data)

    def test_me_endpoint_requires_jwt(self) -> None:
        resp = self._register(username="hank", email="hank@example.com")

        body = resp.json()
        data = self._as_dict(body.get("data"), "data")
        tokens = self._as_dict(data.get("tokens"), "data.tokens")
        access = self._as_str(tokens.get("access"), "data.tokens.access")

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        me_resp = cast(JsonClientResponse, self.client.get(self.ME_URL))
        self.assertEqual(me_resp.status_code, status.HTTP_200_OK)

        me_body = me_resp.json()
        self.assertEqual(me_body.get("status"), 0)

        me_data = self._as_dict(me_body.get("data"), "data")
        self.assertEqual(me_data.get("username"), "hank")

    def test_password_change_success_and_failure(self) -> None:
        initial_pw = self._pw()
        resp = self._register(
            username="ivy",
            email="ivy@example.com",
            password=initial_pw,
        )

        body = resp.json()
        data = self._as_dict(body.get("data"), "data")
        tokens = self._as_dict(data.get("tokens"), "data.tokens")
        access = self._as_str(tokens.get("access"), "data.tokens.access")

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        bad_resp = cast(
            JsonClientResponse,
            self.client.post(
                self.PW_CHANGE_URL,
                {
                    "old_password": self._pw(),
                    "new_password": self._pw(),
                    "new_password2": self._pw(),
                },
                format="json",
            ),
        )
        self.assertEqual(bad_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bad_resp.json().get("status"), 1)

        new_pw = self._pw()
        good_resp = cast(
            JsonClientResponse,
            self.client.post(
                self.PW_CHANGE_URL,
                {
                    "old_password": initial_pw,
                    "new_password": new_pw,
                    "new_password2": new_pw,
                },
                format="json",
            ),
        )
        self.assertEqual(good_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(good_resp.json().get("status"), 0)

        self.client.credentials()
        relogin = self._login("ivy", new_pw)
        self.assertEqual(relogin.status_code, status.HTTP_200_OK)
