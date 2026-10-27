"""Unit tests for the private FastAPI inference endpoint."""
from io import BytesIO
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from fastapi_service.main import app
from road_damage.detector import DetectorNotConfiguredError, MockDetector
from road_damage.config import DetectorConfig
from road_damage.adapters.ultralytics_adapter import IncompatibleModelLabelsError
from road_damage.schemas import Detection

client = TestClient(app)


def png_bytes():
    buffer = BytesIO()
    Image.new("RGB", (32, 24), (90, 90, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


class RoutIQVisionEndpointTests(unittest.TestCase):
    def test_health_reports_liveness_without_detector_readiness(self):
        with patch("fastapi_service.routers.vision.get_detector") as get_detector:
            response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "routiq-vision"})
        get_detector.assert_not_called()

    def test_detector_status_is_explicit_when_disabled(self):
        with patch("fastapi_service.routers.vision.DetectorConfig.from_env", return_value=DetectorConfig()), \
                patch("fastapi_service.routers.vision.get_detector") as get_detector:
            response = client.get("/detector-status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "disabled")
        self.assertFalse(response.json()["inference_tested"])
        get_detector.assert_not_called()

    def test_detector_status_accepts_configured_hosted_model(self):
        config = DetectorConfig(
            backend="roboflow",
            api_key="test-api-key",
            model_id="road-damages-detection/1",
            api_url="https://detect.roboflow.com",
        )
        with patch("fastapi_service.routers.vision.DetectorConfig.from_env", return_value=config), \\
                patch("fastapi_service.routers.vision.get_detector") as get_detector:
            response = client.get("/detector-status")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "remote_configured")
        self.assertEqual(response.json()["labels"], "not_checked")
        self.assertFalse(response.json()["inference_tested"])
        get_detector.assert_not_called()

    def test_detector_status_reports_missing_weights_without_loading_a_model(self):
        config = DetectorConfig(backend="ultralytics", weights_path="")
        with patch("fastapi_service.routers.vision.DetectorConfig.from_env", return_value=config), \
                patch("fastapi_service.routers.vision.get_detector") as get_detector:
            response = client.get("/detector-status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "missing_weights_path")
        self.assertFalse(response.json()["inference_tested"])
        get_detector.assert_not_called()

    def test_detector_status_reports_missing_file_and_invalid_configuration(self):
        with tempfile.TemporaryDirectory(prefix="routiq-missing-model-test-") as directory:
            config = DetectorConfig(backend="ultralytics", weights_path=f"{directory}/missing.pt")
            with patch("fastapi_service.routers.vision.DetectorConfig.from_env", return_value=config), \
                    patch("fastapi_service.routers.vision.get_detector") as get_detector:
                missing = client.get("/detector-status")
            self.assertEqual(missing.json()["status"], "weights_not_found")
            get_detector.assert_not_called()

        with patch("fastapi_service.routers.vision.DetectorConfig.from_env", side_effect=ValueError("private configuration")):
            invalid = client.get("/detector-status")
        self.assertEqual(invalid.json()["status"], "invalid_configuration")
        self.assertNotIn("private configuration", invalid.text)

    def test_detector_status_reports_missing_inference_dependency_and_model_load_failure(self):
        config = DetectorConfig(backend="ultralytics", weights_path="existing-model.pt")
        for failure, expected in ((ImportError("missing dependency"), "dependency_missing"),
                                  (RuntimeError("private model error"), "model_load_failed")):
            with self.subTest(expected=expected), \
                    patch("fastapi_service.routers.vision.DetectorConfig.from_env", return_value=config), \
                    patch.object(DetectorConfig, "preflight", return_value={"status": "weights_present_unverified", "labels": "not_checked"}), \
                    patch("fastapi_service.routers.vision.get_detector", side_effect=failure):
                response = client.get("/detector-status")
            self.assertEqual(response.json()["status"], expected)
            self.assertNotIn("private model error", response.text)
            self.assertFalse(response.json()["inference_tested"])

    def test_detector_status_reports_compatible_loaded_classes_without_claiming_inference(self):
        class LoadedDetector:
            registry = {0: "pothole", 1: "longitudinal_crack"}

        config = DetectorConfig(backend="ultralytics", weights_path="existing-model.pt")
        with patch("fastapi_service.routers.vision.DetectorConfig.from_env", return_value=config), \
                patch.object(DetectorConfig, "preflight", return_value={"status": "weights_present_unverified", "labels": "not_checked"}), \
                patch("fastapi_service.routers.vision.get_detector", return_value=LoadedDetector()):
            response = client.get("/detector-status")
        self.assertEqual(response.json()["status"], "ready_to_test")
        self.assertEqual(response.json()["labels"], "compatible")
        self.assertFalse(response.json()["inference_tested"])

    def test_detector_status_reports_incompatible_loaded_labels(self):
        config = DetectorConfig(backend="ultralytics", weights_path="existing-model.pt")
        with patch("fastapi_service.routers.vision.DetectorConfig.from_env", return_value=config), \
                patch.object(DetectorConfig, "preflight", return_value={"status": "weights_present_unverified", "labels": "not_checked"}), \
                patch("fastapi_service.routers.vision.get_detector", side_effect=IncompatibleModelLabelsError("unsupported label")):
            response = client.get("/detector-status")
        self.assertEqual(response.json()["status"], "incompatible_labels")

    def test_detect_returns_mocked_inference_without_writing_database(self):
        detection = Detection(
            class_id=3, class_name="pothole", confidence=0.91,
            bbox=(1, 2, 20, 21), model_name="test-model", model_version="test",
        )
        with patch("fastapi_service.routers.vision.get_detector", return_value=MockDetector([detection])):
            response = client.post(
                "/detect", content=png_bytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["detections"][0]["class_name"], "pothole")

    def test_invalid_image_bytes_are_rejected(self):
        response = client.post(
            "/detect", content=b"not an image",
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_unconfigured_model_returns_503(self):
        class Disabled:
            def detect(self, image):
                raise DetectorNotConfiguredError("disabled for test")
        with patch("fastapi_service.routers.vision.get_detector", return_value=Disabled()):
            response = client.post(
                "/detect", content=png_bytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
        self.assertEqual(response.status_code, 503, response.text)


if __name__ == "__main__":
    unittest.main()
