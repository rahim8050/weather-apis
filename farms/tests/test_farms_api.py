from __future__ import annotations

import secrets

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

User = get_user_model()


class FarmsApiTests(APITestCase):
    def setUp(self) -> None:
        pw = secrets.token_urlsafe(12)
        self.user1 = User.objects.create_user(username="u1", password=pw)
        self.user2 = User.objects.create_user(username="u2", password=pw)

    def test_user_sees_only_their_farms(self) -> None:
        self.client.force_authenticate(user=self.user1)
        r1 = self.client.post(
            "/api/v1/farms/", {"name": "Farm A"}, format="json"
        )
        self.assertEqual(r1.status_code, 201)

        self.client.force_authenticate(user=self.user2)
        r2 = self.client.post(
            "/api/v1/farms/", {"name": "Farm B"}, format="json"
        )
        self.assertEqual(r2.status_code, 201)

        self.client.force_authenticate(user=self.user1)
        lst = self.client.get("/api/v1/farms/")
        self.assertEqual(lst.status_code, 200)
        names = [x["name"] for x in lst.json()]
        self.assertEqual(names, ["Farm A"])

    def test_invalid_bbox_rejected(self) -> None:
        self.client.force_authenticate(user=self.user1)
        bad = {
            "name": "Bad AOI",
            "bbox_south": -1.0,
            "bbox_west": 36.0,
            "bbox_north": -2.0,  # north < south
            "bbox_east": 37.0,
        }
        res = self.client.post("/api/v1/farms/", bad, format="json")
        self.assertEqual(res.status_code, 400)
