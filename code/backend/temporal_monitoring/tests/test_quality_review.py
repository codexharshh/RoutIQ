import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from temporal_monitoring.status_assessment import compare_observations


class QualityAwareComparisonTests(unittest.TestCase):
    def observation(self, *, observed_at=None, latitude=28.6139, longitude=77.2090,
                    accuracy=4, confidence=0.9):
        return SimpleNamespace(
            observed_at=observed_at,
            latitude=latitude,
            longitude=longitude,
            gps_accuracy_m=accuracy,
            confidence=confidence,
            damage_class="pothole",
            metadata={"image_width": 1280, "image_height": 720},
        )

    def test_missing_timestamps_abstain(self):
        result = compare_observations(
            self.observation(),
            self.observation(longitude=77.20901),
        )
        self.assertEqual(result["decision"], "uncertain")
        self.assertTrue(result["abstained"])
        self.assertTrue(any("timestamps are unavailable" in item for item in result["reasons"]))

    def test_observations_with_sufficient_positive_evidence_are_candidates_only(self):
        first = datetime(2026, 1, 1, tzinfo=timezone.utc)
        second = datetime(2026, 1, 2, tzinfo=timezone.utc)
        result = compare_observations(
            self.observation(observed_at=first),
            self.observation(observed_at=second, longitude=77.20901),
        )
        self.assertEqual(result["decision"], "same_damage")
        self.assertEqual(result["repair_verification"], "not_inferred")


if __name__ == "__main__":
    unittest.main()
