from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase


class RoutIQAccountApiTests(APITestCase):
    def test_legacy_public_registration_does_not_grant_staff_access(self):
        response = self.client.post("/accounts/register/", {
            "username": "legacy-citizen",
            "email": "legacy-citizen@example.test",
            "password1": "Test-Pass-4729!",
            "password2": "Test-Pass-4729!",
        })
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="legacy-citizen")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_registration_creates_non_staff_account(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {"username": "harsh-routiq-test", "email": "harsh-routiq-test@example.test", "password": "Test-Pass-4729!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = get_user_model().objects.get(username="harsh-routiq-test")
        self.assertFalse(user.is_staff)
        self.assertTrue(user.check_password("Test-Pass-4729!"))

    def test_login_returns_access_and_refresh_tokens(self):
        user = get_user_model().objects.create_user(
            username="routiq-login-test", email="routiq-login@example.test", password="Test-Pass-4729!"
        )
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": user.username, "password": "Test-Pass-4729!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("access", response.data.get("data", {}))
        self.assertIn("refresh", response.data.get("data", {}))
        self.assertEqual(response.data["data"]["user"]["username"], user.username)

    def test_login_accepts_email_in_username_field(self):
        user = get_user_model().objects.create_user(
            username="routiq-email-login", email="routiq-email-login@example.test", password="Test-Pass-4729!"
        )
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": " ROUTIQ-EMAIL-LOGIN@EXAMPLE.TEST ", "password": "Test-Pass-4729!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data.get("success"))
        self.assertEqual(response.data["data"]["user"]["username"], user.username)

    def test_invalid_login_returns_401_and_visible_error(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "does-not-exist", "password": "bad-password"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, response.data)
        self.assertFalse(response.data.get("success", True))
        self.assertTrue(response.data.get("message"))

    def test_duplicate_registration_returns_actionable_field_errors(self):
        user_model = get_user_model()
        user_model.objects.create_user(
            username="routiq-existing-user",
            email="routiq-existing@example.test",
            password="Existing-Pass-4729!",
        )
        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "username": "routiq-existing-user",
                "email": "routiq-existing@example.test",
                "password": "New-Pass-4729!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)
        self.assertIn("already exists", response.data["detail"].lower())
        self.assertIn("username", response.data.get("errors", {}))
        self.assertIn("email", response.data.get("errors", {}))
