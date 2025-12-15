from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from api_keys.auth import validate_api_key
from api_keys.models import ApiKey


class ApiKeyTests(APITestCase):
    register_url = "/api/v1/auth/register/"
    keys_url = "/api/v1/keys/"

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

    def test_create_api_key_and_store_only_hash(self) -> None:
        access, _ = self._register_and_login("apiuser")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = self.client.post(
            self.keys_url,
            {"name": "My Key", "expires_at": None},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        body = resp.json()
        self.assertEqual(body["status"], 0)
        plaintext = body["data"]["api_key"]
        self.assertIsNotNone(plaintext)
        api_key = ApiKey.objects.get(id=body["data"]["id"])
        self.assertNotEqual(api_key.key_hash, plaintext)
        self.assertFalse(hasattr(api_key, "api_key"))
        self.assertNotIn("key_hash", body["data"])

    def test_list_api_keys_never_exposes_plaintext(self) -> None:
        access, _ = self._register_and_login("apilist")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        create_resp = self.client.post(
            self.keys_url, {"name": "List Key"}, format="json"
        )
        plaintext = create_resp.json()["data"]["api_key"]
        list_resp = self.client.get(self.keys_url)
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        body = list_resp.json()
        self.assertEqual(body["status"], 0)
        for item in body["data"]:
            self.assertNotIn("api_key", item)
            self.assertNotIn("key_hash", item)
        # ensure stored hash differs from plaintext
        api_key = ApiKey.objects.get(id=create_resp.json()["data"]["id"])
        self.assertNotEqual(api_key.key_hash, plaintext)

    def test_revoke_api_key_and_validate_helper(self) -> None:
        access, _ = self._register_and_login("apirevoke")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        create_resp = self.client.post(
            self.keys_url, {"name": "Revoke Me"}, format="json"
        )
        data = create_resp.json()["data"]
        plaintext = data["api_key"]
        revoke_resp = self.client.delete(f"{self.keys_url}{data['id']}/")
        self.assertEqual(revoke_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(revoke_resp.json()["status"], 0)

        api_key = ApiKey.objects.get(id=data["id"])
        self.assertIsNotNone(api_key.revoked_at)
        self.assertIsNone(validate_api_key(plaintext))

    def test_cannot_revoke_other_users_key(self) -> None:
        access1, _ = self._register_and_login("owner")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access1}")
        create_resp = self.client.post(self.keys_url, {"name": "Owner Key"})
        key_id = create_resp.json()["data"]["id"]

        access2, _ = self._register_and_login("intruder")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access2}")
        resp = self.client.delete(f"{self.keys_url}{key_id}/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.json()["status"], 1)
