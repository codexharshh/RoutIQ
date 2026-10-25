from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from road_observations.models import DamageInstance, DamageObservation, InspectionSession, ObservationMatch


class TemporalEvidenceReviewTests(APITestCase):
    endpoint = "/api/v1/road-observations/temporal-review/"

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="routiq-temporal-owner", password="safe-pass-123")
        self.other = User.objects.create_user(username="routiq-temporal-other", password="safe-pass-123")

    def observation(self, owner, *, damage_class="pothole", latitude=28.6139, longitude=77.2090,
                    confidence=0.90, minutes_ago=1440, gps_accuracy_m=4, image_size=(1280, 720)):
        session = InspectionSession.objects.create(owner=owner, title="Temporal test pass")
        instance = DamageInstance.objects.create(
            created_by=owner, damage_class=damage_class, current_status="unknown",
            latitude=latitude, longitude=longitude,
        )
        metadata = {}
        if image_size:
            metadata = {"image_width": image_size[0], "image_height": image_size[1]}
        return DamageObservation.objects.create(
            session=session, instance=instance, damage_class=damage_class,
            confidence=confidence, latitude=latitude, longitude=longitude,
            gps_accuracy_m=gps_accuracy_m, observed_at=timezone.now() - timedelta(minutes=minutes_ago),
            metadata=metadata,
        )

    def review(self, a, b, **overrides):
        payload = {"observation_a_id": a.pk, "observation_b_id": b.pk, "distance_threshold_m": 15}
        payload.update(overrides)
        return self.client.post(self.endpoint, payload, format="json")

    def test_close_quality_observations_are_saved_as_a_repeat_sighting_candidate(self):
        a = self.observation(self.owner, minutes_ago=2880)
        b = self.observation(self.owner, longitude=77.20904, minutes_ago=0)
        self.client.force_authenticate(user=self.owner)
        response = self.review(a, b)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["decision"], "same_damage")
        self.assertFalse(response.data["abstained"])
        self.assertEqual(response.data["repair_verification"], "not_inferred")
        self.assertEqual(ObservationMatch.objects.count(), 1)

    def test_low_quality_observations_abstain(self):
        a = self.observation(self.owner, minutes_ago=2880, confidence=0.20, gps_accuracy_m=150, image_size=(100, 80))
        b = self.observation(self.owner, longitude=77.20902, minutes_ago=0, confidence=0.25, gps_accuracy_m=150, image_size=(100, 80))
        self.client.force_authenticate(user=self.owner)
        response = self.review(a, b)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["decision"], "uncertain")
        self.assertTrue(response.data["abstained"])
        self.assertTrue(response.data["reasons"])

    def test_missing_gps_abstains_without_inventing_distance(self):
        a = self.observation(self.owner, minutes_ago=2880, latitude=None, longitude=None)
        b = self.observation(self.owner, minutes_ago=0)
        self.client.force_authenticate(user=self.owner)
        response = self.review(a, b)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["decision"], "uncertain")
        self.assertIsNone(response.data["distance_m"])

    def test_invalid_stored_coordinates_abstain_without_server_error(self):
        a = self.observation(self.owner, latitude=95, minutes_ago=2880)
        b = self.observation(self.owner, longitude=77.20902, minutes_ago=0)
        self.client.force_authenticate(user=self.owner)
        response = self.review(a, b)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["decision"], "uncertain")
        self.assertTrue(response.data["abstained"])
        self.assertIsNone(response.data["distance_m"])

    def test_other_users_observations_are_not_revealed(self):
        a = self.observation(self.owner, minutes_ago=2880)
        b = self.observation(self.other, minutes_ago=0)
        self.client.force_authenticate(user=self.owner)
        response = self.review(a, b)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(ObservationMatch.objects.count(), 0)

    def test_same_observation_is_rejected(self):
        a = self.observation(self.owner)
        self.client.force_authenticate(user=self.owner)
        response = self.review(a, a)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_endpoint_requires_authentication(self):
        a = self.observation(self.owner)
        b = self.observation(self.owner, longitude=77.20901, minutes_ago=60)
        response = self.review(a, b)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_threshold_is_range_checked(self):
        a = self.observation(self.owner, minutes_ago=2880)
        b = self.observation(self.owner, longitude=77.20901)
        self.client.force_authenticate(user=self.owner)
        response = self.review(a, b, distance_threshold_m=1000)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_near_threshold_pair_abstains_instead_of_forcing_a_match(self):
        a = self.observation(self.owner, minutes_ago=2880)
        b = self.observation(self.owner, longitude=77.20917, minutes_ago=0)
        self.client.force_authenticate(user=self.owner)
        response = self.review(a, b, distance_threshold_m=15)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["decision"], "uncertain")
        self.assertTrue(response.data["abstained"])
        self.assertTrue(any("near the configured threshold" in reason for reason in response.data["reasons"]))

    def test_invalid_gps_accuracy_abstains_with_explanation(self):
        a = self.observation(self.owner, minutes_ago=2880)
        b = self.observation(self.owner, longitude=77.20901, minutes_ago=0)
        DamageObservation.objects.filter(pk=a.pk).update(gps_accuracy_m=-1)
        self.client.force_authenticate(user=self.owner)
        response = self.review(a, b)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["decision"], "uncertain")
        self.assertTrue(any("GPS accuracy is invalid" in reason for reason in response.data["reasons"]))

    def test_non_finite_threshold_is_rejected(self):
        a = self.observation(self.owner, minutes_ago=2880)
        b = self.observation(self.owner, longitude=77.20901)
        self.client.force_authenticate(user=self.owner)
        response = self.review(a, b, distance_threshold_m="NaN")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
