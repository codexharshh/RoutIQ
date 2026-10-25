from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from road_observations.models import DamageObservation, InspectionSession


class DamageObservationValidationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="observation-model-owner", password="test-only")
        self.session = InspectionSession.objects.create(owner=self.owner, source_kind="image")

    def make_observation(self, **overrides):
        values = {
            "session": self.session,
            "damage_class": "pothole",
            "confidence": 0.75,
            "latitude": Decimal("28.6139000"),
            "longitude": Decimal("77.2090000"),
            "bbox": [1, 2, 30, 40],
        }
        values.update(overrides)
        return DamageObservation(**values)

    def test_valid_observation_passes_model_validation(self):
        observation = self.make_observation()
        observation.full_clean()
        self.assertEqual(observation.damage_class, "pothole")

    def test_latitude_and_longitude_must_be_supplied_together(self):
        observation = self.make_observation(longitude=None)
        with self.assertRaises(ValidationError) as context:
            observation.clean()
        self.assertIn("latitude", context.exception.message_dict)

    def test_coordinates_must_be_in_geographic_ranges(self):
        for overrides in (
            {"latitude": Decimal("91"), "longitude": Decimal("10")},
            {"latitude": Decimal("10"), "longitude": Decimal("181")},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.make_observation(**overrides).clean()

    def test_bbox_must_have_increasing_non_negative_coordinates(self):
        for bbox in ([1, 2, 1, 4], [-1, 2, 4, 5], [1, 2, 3], [1, 2, float("nan"), 4]):
            with self.subTest(bbox=bbox), self.assertRaises(ValidationError):
                self.make_observation(bbox=bbox).clean()
