import unittest
from unittest.mock import Mock, patch

from PIL import Image
import requests

from road_observations.vision_client import (
    FastAPIVisionClient,
    VisionReadinessError,
    VisionServiceTimeout,
    VisionServiceUnavailable,
)


class FastAPIVisionClientTests(unittest.TestCase):
    def test_detector_status_is_sanitized(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "status": "ready_to_test", "labels": "compatible", "inference_tested": False,
            "weights_path": "private/path/weights.pt", "class_ids": [0, 1],
        }
        with patch("road_observations.vision_client.requests.get", return_value=response):
            result = FastAPIVisionClient().detector_status()
        self.assertEqual(result, {"status": "ready_to_test", "labels": "compatible", "inference_tested": False})

    def test_remote_configured_detector_status_is_sanitized(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "status": "remote_configured",
            "labels": "not_checked",
            "inference_tested": False,
            "service": "routiq-vision",
        }
        with patch("road_observations.vision_client.requests.get", return_value=response):
            result = FastAPIVisionClient().detector_status()
        self.assertEqual(result, {
            "status": "remote_configured",
            "labels": "not_checked",
            "inference_tested": False,
        })

    def test_malformed_detector_status_is_rejected(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"status": ["ready_to_test"], "labels": "compatible"}
        with patch("road_observations.vision_client.requests.get", return_value=response):
            with self.assertRaisesRegex(VisionReadinessError, "invalid readiness response"):
                FastAPIVisionClient().detector_status()

    def test_detector_status_distinguishes_unreachable_and_timeout(self):
        with patch("road_observations.vision_client.requests.get", side_effect=requests.ConnectionError()):
            with self.assertRaises(VisionServiceUnavailable):
                FastAPIVisionClient().detector_status()
        with patch("road_observations.vision_client.requests.get", side_effect=requests.Timeout()):
            with self.assertRaises(VisionServiceTimeout):
                FastAPIVisionClient().detector_status()

    def test_detector_status_rejects_invalid_json_and_http_errors(self):
        invalid_json = Mock(ok=True, status_code=200)
        invalid_json.json.side_effect = ValueError("private response contents")
        http_error = Mock(ok=False, status_code=503)
        with patch("road_observations.vision_client.requests.get", side_effect=[invalid_json, http_error]):
            with self.assertRaises(VisionReadinessError):
                FastAPIVisionClient().detector_status()
            with self.assertRaises(VisionReadinessError):
                FastAPIVisionClient().detector_status()

    def test_health_response_does_not_claim_detector_readiness(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"status": "ok", "service": "routiq-vision"}
        with patch("road_observations.vision_client.requests.get", return_value=response) as get:
            result = FastAPIVisionClient().health()
        self.assertEqual(result, {"status": "ok", "service": "routiq-vision"})
        self.assertTrue(get.call_args.args[0].endswith("/health"))

    def test_valid_detection_response_is_parsed_and_validated(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "count": 1,
            "detections": [{
                "class_id": 3,
                "class_name": "pothole",
                "confidence": 0.8,
                "bbox": [1, 2, 10, 12],
                "model_name": "test-model",
                "model_version": "test-version",
            }],
        }
        with patch("road_observations.vision_client.requests.post", return_value=response) as post:
            detections = FastAPIVisionClient().detect(Image.new("RGB", (16, 16)))
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].class_name, "pothole")
        self.assertEqual(post.call_args.kwargs["headers"]["Content-Type"], "application/octet-stream")

    def test_large_image_is_encoded_under_the_request_cap_and_boxes_are_rescaled(self):
        from unittest.mock import patch

        from PIL import Image

        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "count": 1,
            "detections": [{
                "class_id": 3,
                "class_name": "pothole",
                "confidence": 0.8,
                "bbox": [1, 2, 10, 12],
                "model_name": "test-model",
                "model_version": "test-version",
            }],
        }
        image = Image.effect_noise((1200, 800), 100).convert("RGB")
        with patch("road_observations.vision_client.MAX_VISION_REQUEST_BYTES", 100_000), \
                patch("road_observations.vision_client.requests.post", return_value=response) as post:
            detections = FastAPIVisionClient().detect(image)

        payload = post.call_args.kwargs["data"]
        self.assertLessEqual(len(payload), 100_000)
        self.assertEqual(post.call_args.kwargs["headers"]["Content-Type"], "application/octet-stream")
        self.assertGreater(detections[0].bbox[2], 10)
        self.assertGreater(detections[0].bbox[3], 12)

    def test_inconsistent_detection_count_is_rejected(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"count": 2, "detections": []}
        with patch("road_observations.vision_client.requests.post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "inconsistent detection count"):
                FastAPIVisionClient().detect(Image.new("RGB", (16, 16)))

    def test_invalid_detection_output_is_rejected(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"count": 1, "detections": [{"class_id": 3}]}
        with patch("road_observations.vision_client.requests.post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "malformed detection"):
                FastAPIVisionClient().detect(Image.new("RGB", (16, 16)))


if __name__ == "__main__":
    unittest.main()
