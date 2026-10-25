import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from django.test import override_settings

from road_observations.management.commands.routiq_preflight import (
    Command,
    _allowlist_check,
    _evidence_root_check,
    _production_security_check,
    _service_url_check,
)


class RoutIQPreflightTests(unittest.TestCase):
    def test_allowlist_validation_rejects_wildcards_and_credentialed_cors(self):
        self.assertEqual(_allowlist_check(["*"], ["https://example.org"], ["https://example.org"], False, False)[0], "BLOCKED")
        self.assertEqual(_allowlist_check(["example.org"], ["https://example.org"], ["https://example.org"], False, True)[0], "BLOCKED")
        self.assertEqual(_allowlist_check(["example.org"], ["https://example.org"], ["https://example.org"], False, False)[0], "PASS")

    def test_private_evidence_path_must_not_be_inside_public_roots(self):
        with tempfile.TemporaryDirectory(prefix="routiq-preflight-") as directory:
            root = Path(directory)
            media, static, private = root / "media", root / "static", root / "private"
            media.mkdir()
            static.mkdir()
            self.assertEqual(_evidence_root_check(media / "private", media, static)[0], "BLOCKED")
            self.assertEqual(_evidence_root_check(private, media, static)[0], "PASS")

    def test_service_url_validation_never_echoes_embedded_credentials(self):
        state, detail = _service_url_check("http://private-user:private-password@127.0.0.1:8100", 8100)
        self.assertEqual(state, "BLOCKED")
        self.assertNotIn("private-password", detail)

    def test_production_security_requires_https_and_secure_cookies(self):
        self.assertEqual(_production_security_check(False, True, True, True)[0], "PASS")
        self.assertEqual(_production_security_check(True, True, True, True)[0], "BLOCKED")
        self.assertEqual(_production_security_check(False, False, True, True)[0], "BLOCKED")
        self.assertEqual(_production_security_check(False, True, False, True)[0], "BLOCKED")
        self.assertEqual(_production_security_check(False, True, True, False)[0], "BLOCKED")

    def test_preflight_output_is_sanitized_and_inference_is_not_overstated(self):
        with tempfile.TemporaryDirectory(prefix="routiq-preflight-") as directory:
            root = Path(directory)
            media, static = root / "media", root / "static"
            media.mkdir()
            static.mkdir()
            stdout = StringIO()
            loader = Mock()
            loader.graph.leaf_nodes.return_value = [("road_observations", "0002_inspection_evidence")]
            loader.applied_migrations = {("road_observations", "0001_initial")}
            with override_settings(
                SECRET_KEY="private-secret-value-that-must-not-be-printed",
                DEBUG=True,
                ALLOWED_HOSTS=["localhost"],
                CORS_ALLOWED_ORIGINS=["http://localhost:5173"],
                CSRF_TRUSTED_ORIGINS=["http://localhost:5173"],
                CORS_ALLOW_ALL_ORIGINS=False,
                CORS_ALLOW_CREDENTIALS=False,
                MEDIA_ROOT=media,
                STATIC_ROOT=static,
                ROUTIQ_PRIVATE_EVIDENCE_ROOT=root / "private",
            ), patch("road_observations.management.commands.routiq_preflight.MigrationLoader", return_value=loader), \
                    patch("road_observations.vision_client.FastAPIVisionClient.health", return_value={"status": "ok", "service": "routiq-vision"}), \
                    patch("road_observations.vision_client.FastAPIVisionClient.detector_status", return_value={
                        "status": "ready_to_test", "labels": "compatible", "inference_tested": False,
                    }):
                Command(stdout=stdout).handle(skip_service_checks=False)
        output = stdout.getvalue()
        self.assertIn("[PASS] Django secret configuration", output)
        self.assertIn("[WARNING] FastAPI detector readiness", output)
        self.assertIn("real inference has not been verified", output)
        self.assertNotIn("private-secret-value", output)

    def test_skip_service_checks_does_not_make_network_requests(self):
        with tempfile.TemporaryDirectory(prefix="routiq-preflight-") as directory:
            root = Path(directory)
            loader = Mock()
            loader.graph.leaf_nodes.return_value = []
            loader.applied_migrations = set()
            output = StringIO()
            with patch("road_observations.management.commands.routiq_preflight.MigrationLoader", return_value=loader), \
                    patch("road_observations.vision_client.FastAPIVisionClient.health") as health, \
                    patch("road_observations.vision_client.FastAPIVisionClient.detector_status") as service:
                Command(stdout=output).handle(skip_service_checks=True)
            health.assert_not_called()
            service.assert_not_called()
        self.assertIn("[NOT VERIFIED] FastAPI detector readiness", output.getvalue())

    def test_network_and_readiness_failures_are_reported_separately(self):
        from road_observations.vision_client import VisionServiceTimeout, VisionServiceUnavailable
        loader = Mock()
        loader.graph.leaf_nodes.return_value = []
        loader.applied_migrations = set()
        output = StringIO()
        with patch("road_observations.management.commands.routiq_preflight.MigrationLoader", return_value=loader), \
                patch("road_observations.vision_client.FastAPIVisionClient.health", side_effect=VisionServiceUnavailable()), \
                patch("road_observations.vision_client.FastAPIVisionClient.detector_status", side_effect=VisionServiceTimeout()):
            Command(stdout=output).handle(skip_service_checks=False)
        self.assertIn("[BLOCKED] FastAPI service health: The vision service is unreachable.", output.getvalue())
        self.assertIn("[BLOCKED] FastAPI detector readiness: The readiness request timed out.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
