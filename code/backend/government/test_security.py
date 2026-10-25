from django.core.cache import cache
from rest_framework.test import APITestCase

from .models import GovUser, RoadSegment


class GovernmentEndpointSecurityTests(APITestCase):
    databases = {"default", "government"}

    def setUp(self):
        cache.clear()
        self.gov_user = GovUser.objects.db_manager("government").create_user(
            username="routiq-test-gov",
            email="gov@example.test",
            password="Safe-Test-Pass-8742!",
            full_name="Test Officer",
            department="Roads",
        )
        self.gov_user.save(using="government")

    def road_segment_payload(self):
        return {
            "points": [[28.6139, 77.2090], [28.6149, 77.2100]],
            "contractor_id": "CNT-001",
            "contractor_name": "Roads Ltd",
            "contractor_email": "contractor@example.test",
            "contractor_phone": "+911234567890",
            "road_creation_date": "2024-01-01",
            "warranty_period": 12,
            "money_sanctioned": "100000.00",
        }

    def test_anonymous_cannot_write_road_segments(self):
        response = self.client.post(
            "/gov-api/road-segments/",
            self.road_segment_payload(),
            format="json",
        )
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(RoadSegment.objects.using("government").count(), 0)

    def test_government_login_token_can_create_road_segment(self):
        login = self.client.post(
            "/gov-api/auth/login/",
            {"username": "routiq-test-gov", "password": "Safe-Test-Pass-8742!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.data)
        token = login.data["token"]

        response = self.client.post(
            "/gov-api/road-segments/",
            self.road_segment_payload(),
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(RoadSegment.objects.using("government").count(), 1)
        self.assertEqual(response.data["created_by"]["username"], "routiq-test-gov")

    def test_invalid_government_bearer_is_rejected_for_writes(self):
        response = self.client.post(
            "/gov-api/road-segments/",
            self.road_segment_payload(),
            format="json",
            HTTP_AUTHORIZATION="Bearer not-a-signed-token",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(RoadSegment.objects.using("government").count(), 0)

    def test_anonymous_signup_is_not_allowed(self):
        response = self.client.post(
            "/gov-api/auth/signup/",
            {
                "username": "unapproved-gov",
                "email": "unapproved@example.test",
                "password": "Safe-Test-Pass-8742!",
                "full_name": "Unapproved",
                "department": "Roads",
            },
            format="json",
        )
        self.assertIn(response.status_code, (401, 403))
        self.assertFalse(GovUser.objects.using("government").filter(username="unapproved-gov").exists())

    def test_government_login_is_rate_limited(self):
        for _ in range(10):
            self.client.post(
                "/gov-api/auth/login/",
                {"username": "routiq-test-gov", "password": "wrong-password"},
                format="json",
            )

        response = self.client.post(
            "/gov-api/auth/login/",
            {"username": "routiq-test-gov", "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(response.status_code, 429)
