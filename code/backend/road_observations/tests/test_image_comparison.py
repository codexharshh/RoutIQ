from types import SimpleNamespace
from django.test import SimpleTestCase
from road_observations.image_comparison import compare_session_images


class SessionImageComparisonTests(SimpleTestCase):
    def test_same_session_is_rejected(self):
        session = SimpleNamespace(pk=1, image_evidence=None, evidence_expires_at=None)
        result = compare_session_images(session, session)
        self.assertFalse(result["available"])
        self.assertEqual(result["status"], "insufficient_evidence")

    def test_missing_private_evidence_abstains(self):
        first = SimpleNamespace(pk=1, image_evidence=None, evidence_expires_at=None)
        second = SimpleNamespace(pk=2, image_evidence=None, evidence_expires_at=None)
        result = compare_session_images(first, second)
        self.assertFalse(result["available"])
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertIn("No retained image", result["explanation"])
