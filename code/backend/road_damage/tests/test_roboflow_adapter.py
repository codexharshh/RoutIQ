import unittest
from unittest.mock import Mock, patch

from PIL import Image

from road_damage.config import DetectorConfig
from road_damage.detector import DetectorNotConfiguredError
from road_damage.adapters.roboflow_adapter import RoboflowAdapter


class RoboflowAdapterTests(unittest.TestCase):
    def _config(self, **overrides):
        values = {
            "backend": "roboflow",
            "api_key": "test-only-api-key",
            "model_id": "road-damages-detection/1",
            "api_url": "https://detect.roboflow.com",
            "confidence_threshold": 0.25,
        }
        values.update(overrides)
        return DetectorConfig(**values)

    def test_preflight_requires_key_and_reports_remote_configuration(self):
        self.assertEqual(
            DetectorConfig(backend="roboflow").preflight()["status"],
            "missing_api_key",
        )
        self.assertEqual(
            self._config().preflight()["status"],
            "remote_configured",
        )

    def test_missing_key_fails_closed(self):
        with self.assertRaises(DetectorNotConfiguredError):
            RoboflowAdapter(self._config(api_key=""))

    def test_maps_four_supported_classes_and_skips_other_public_model_labels(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "predictions": [
                {"class": "D00", "class_id": 0, "confidence": 0.80,
                 "x": 50, "y": 50, "width": 40, "height": 20},
                {"class": "D40", "class_id": 3, "confidence": 0.91,
                 "x": 100, "y": 50, "width": 20, "height": 20},
                {"class": "D43", "class_id": 4, "confidence": 0.99,
                 "x": 30, "y": 25, "width": 10, "height": 10},
            ]
        }
        image = Image.new("RGB", (200, 100), (120, 120, 120))
        adapter = RoboflowAdapter(self._config())

        with patch(
            "road_damage.adapters.roboflow_adapter.requests.post",
            return_value=response,
        ) as post:
            detections = adapter.detect(image)

        self.assertEqual([item.class_name for item in detections],
                         ["longitudinal_crack", "pothole"])
        self.assertEqual(detections[0].bbox, (30.0, 40.0, 70.0, 60.0))
        self.assertEqual(detections[1].bbox, (90.0, 40.0, 110.0, 60.0))
        self.assertEqual(post.call_args.kwargs["params"]["confidence"], 25)
        self.assertEqual(post.call_args.kwargs["params"]["api_key"], "test-only-api-key")
        self.assertEqual(post.call_args.kwargs["timeout"], (5.0, 45.0))


if __name__ == "__main__":
    unittest.main()
