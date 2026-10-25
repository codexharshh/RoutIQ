import tempfile
import unittest
from pathlib import Path

from road_damage.class_mapping import UnknownDamageClassError, build_class_registry
from road_damage.config import DetectorConfig
from road_damage.detector import DetectorNotConfiguredError, create_detector
from road_damage.schemas import Detection


class DetectorConfigurationTests(unittest.TestCase):
    def test_disabled_backend_is_distinguished(self):
        self.assertEqual(DetectorConfig().preflight()["status"], "disabled")

    def test_mock_backend_cannot_serve_application_requests(self):
        with self.assertRaises(DetectorNotConfiguredError):
            create_detector(DetectorConfig(backend="mock"))

    def test_missing_weights_path_is_distinguished(self):
        config = DetectorConfig(backend="ultralytics")
        self.assertEqual(config.preflight()["status"], "missing_weights_path")

    def test_missing_weights_file_is_distinguished(self):
        config = DetectorConfig(backend="ultralytics", weights_path="missing-routiq-model.pt")
        self.assertEqual(config.preflight()["status"], "weights_not_found")

    def test_present_weights_are_reported_unverified_without_loading(self):
        with tempfile.TemporaryDirectory(prefix="routiq-weights-preflight-") as directory:
            weights = Path(directory) / "model.pt"
            weights.write_bytes(b"metadata-only-placeholder")
            config = DetectorConfig(backend="ultralytics", weights_path=str(weights))
            self.assertEqual(config.preflight()["status"], "weights_present_unverified")

    def test_class_mapping_rejects_unknown_label(self):
        with self.assertRaises(UnknownDamageClassError):
            build_class_registry({0: "road debris"})

    def test_detection_rejects_invalid_model_output(self):
        valid = {"class_id": 0, "class_name": "pothole", "confidence": 0.8,
                 "bbox": (0, 0, 10, 10), "model_name": "model"}
        for invalid in (
            {**valid, "class_name": "unknown"},
            {**valid, "confidence": float("nan")},
            {**valid, "bbox": (0, 0, 0, 10)},
            {**valid, "bbox": (0, 0, float("inf"), 10)},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Detection(**invalid)


if __name__ == "__main__":
    unittest.main()
