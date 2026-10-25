from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from road_observations.models import DamageInstance, DamageObservation, InspectionSession


class ObservationLocationUpdateTests(APITestCase):
    endpoint = "/api/v1/road-observations/{}/location/"

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="routiq-location-owner", password="test-pass-123")
        self.other = User.objects.create_user(username="routiq-location-other", password="test-pass-123")

    def make_observation(self, owner, name):
        session = InspectionSession.objects.create(owner=owner, title=f"Photo inspection {name}")
        instance = DamageInstance.objects.create(
            created_by=owner,
            damage_class="pothole",
            current_status="unknown",
        )
        return DamageObservation.objects.create(
            session=session,
            instance=instance,
            damage_class="pothole",
            confidence=0.656,
            latitude=None,
            longitude=None,
            bbox=[10, 12, 40, 45],
        )

    def test_owner_can_add_coordinates_to_saved_observation(self):
        observation = self.make_observation(self.owner, "own")
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            self.endpoint.format(observation.pk),
            {"latitude": "28.6139", "longitude": "77.2090"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["map_ready"])
        observation.refresh_from_db()
        observation.instance.refresh_from_db()
        self.assertAlmostEqual(float(observation.latitude), 28.6139)
        self.assertAlmostEqual(float(observation.longitude), 77.2090)
        self.assertAlmostEqual(float(observation.instance.latitude), 28.6139)
        self.assertAlmostEqual(float(observation.instance.longitude), 77.2090)

    def test_user_cannot_update_another_users_observation(self):
        observation = self.make_observation(self.other, "other")
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            self.endpoint.format(observation.pk),
            {"latitude": 28.6139, "longitude": 77.2090},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_both_coordinates_are_required(self):
        observation = self.make_observation(self.owner, "partial")
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            self.endpoint.format(observation.pk),
            {"latitude": 28.6139},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_coordinates_are_range_checked(self):
        observation = self.make_observation(self.owner, "range")
        self.client.force_authenticate(user=self.owner)
        for latitude, longitude in ((95, 190), ("NaN", 20), (20, "Infinity")):
            with self.subTest(latitude=latitude, longitude=longitude):
                response = self.client.patch(
                    self.endpoint.format(observation.pk),
                    {"latitude": latitude, "longitude": longitude},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_location_update_requires_authentication(self):
        observation = self.make_observation(self.owner, "anonymous")
        response = self.client.patch(
            self.endpoint.format(observation.pk),
            {"latitude": 28.6139, "longitude": 77.2090},
            format="json",
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
