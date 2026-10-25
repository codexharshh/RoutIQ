from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from road_observations.models import DamageInstance, DamageObservation, InspectionSession
from road_observations.services.observation_service import create_observation


class ObservationServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="observation-service-owner", password="test-only")
        self.other = user_model.objects.create_user(username="observation-service-other", password="test-only")
        self.session = InspectionSession.objects.create(owner=self.owner, source_kind="image")

    def data(self, **overrides):
        values = {
            "session": self.session,
            "damage_class": "pothole",
            "confidence": 0.9,
            "idempotency_key": "upload-123",
            "source_name": "road.jpg",
            "metadata": {"source": "test"},
        }
        values.update(overrides)
        return values

    def test_create_observation_creates_owner_scoped_instance(self):
        observed_at = timezone.now()
        observation, created = create_observation(owner=self.owner, validated_data=self.data(observed_at=observed_at))
        self.assertTrue(created)
        self.assertEqual(observation.session_id, self.session.id)
        self.assertEqual(observation.instance.created_by_id, self.owner.id)
        self.assertEqual(observation.instance.damage_class, "pothole")
        self.assertEqual(DamageObservation.objects.count(), 1)
        self.assertEqual(DamageInstance.objects.count(), 1)

    def test_idempotency_key_prevents_duplicate_observations(self):
        first, created_first = create_observation(owner=self.owner, validated_data=self.data())
        second, created_second = create_observation(owner=self.owner, validated_data=self.data())
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(DamageObservation.objects.count(), 1)

    def test_foreign_session_is_rejected(self):
        with self.assertRaises(PermissionDenied):
            create_observation(owner=self.other, validated_data=self.data())
        self.assertEqual(DamageObservation.objects.count(), 0)

    def test_observation_updates_first_and_last_seen_for_existing_instance(self):
        now = timezone.now()
        instance = DamageInstance.objects.create(
            created_by=self.owner,
            damage_class="pothole",
            first_seen_at=now,
            last_seen_at=now,
        )
        earlier = now - timedelta(days=2)
        observation, created = create_observation(
            owner=self.owner,
            validated_data=self.data(instance=instance, observed_at=earlier, idempotency_key="older-pass"),
        )
        instance.refresh_from_db()
        self.assertTrue(created)
        self.assertEqual(observation.instance_id, instance.id)
        self.assertEqual(instance.first_seen_at, earlier)
        self.assertEqual(instance.last_seen_at, now)
