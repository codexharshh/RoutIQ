import unittest
from types import SimpleNamespace

from road_damage.config import DetectorConfig
from road_damage.detector import (
    DetectorNotConfiguredError,
    DisabledDetector,
    MockDetector,
    create_detector,
)
from road_damage.schemas import Detection


class DetectorTests(unittest.TestCase):
    def test_mock_detector_returns_only_configured_detections(self):
        detection = Detection(0, "pothole", 0.8, (1, 2, 10, 12), model_name="test-model")
        detector = MockDetector([detection])
        self.assertEqual(detector.detect(SimpleNamespace()), [detection])

    def test_mock_detector_rejects_missing_image(self):
        with self.assertRaisesRegex(ValueError, "cannot be None"):
            MockDetector().detect(None)

    def test_disabled_detector_reports_not_configured(self):
        with self.assertRaises(DetectorNotConfiguredError):
            DisabledDetector().detect(object())

    def test_create_detector_returns_disabled_backend_by_default(self):
        detector = create_detector(DetectorConfig(backend="disabled"))
        self.assertIsInstance(detector, DisabledDetector)

    def test_mock_backend_cannot_be_created_for_application_requests(self):
        with self.assertRaises(DetectorNotConfiguredError):
            create_detector(DetectorConfig(backend="mock"))

    def test_unsupported_backend_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported detector backend"):
            create_detector(DetectorConfig(backend="other"))


if __name__ == "__main__":
    unittest.main()
