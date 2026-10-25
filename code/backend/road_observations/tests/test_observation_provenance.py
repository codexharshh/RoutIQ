from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from road_observations.models import DamageObservation, InspectionSession


class ObservationProvenanceTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="routiq-observation-user",
            password="Safe-Test-Pass-8742!",
        )
        self.session = InspectionSession.objects.create(owner=self.user, title="Manual API test")
        self.client.force_authenticate(self.user)

    def test_generic_observation_endpoint_cannot_claim_model_prediction(self):
        response = self.client.post(
            "/api/v1/road-observations/",
            {
                "session": self.session.pk,
                "damage_class": "pothole",
                "class_id": 3,
                "confidence": 0.99,
                "bbox": [1, 2, 30, 40],
                "latitude": 28.6139,
                "longitude": 77.2090,
                "model_name": "fabricated-model",
                "model_version": "fabricated-version",
                "source_name": "fake-inference.jpg",
                "metadata": {
                    "coordinate_source": "manual",
                    "observation_source": "model_inference",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        observation = DamageObservation.objects.get(pk=response.data["id"])
        self.assertIsNone(observation.class_id)
        self.assertEqual(observation.confidence, 0.0)
        self.assertIsNone(observation.bbox)
        self.assertEqual(observation.model_name, "")
        self.assertEqual(observation.model_version, "")
        self.assertEqual(observation.source_name, "manual-api-report")
        self.assertEqual(observation.metadata["observation_source"], "manual")
