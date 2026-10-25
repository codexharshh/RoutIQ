import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import Pothole


class DashcamUploadSecurityTests(APITestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.settings_override.enable()
        self.user = get_user_model().objects.create_user(username="dashcam-user", password="Test-Pass-4729!")
        self.client.force_authenticate(self.user)

    def tearDown(self):
        self.settings_override.disable()
        self.temp_dir.cleanup()

    def test_video_upload_uses_generated_user_scoped_name(self):
        upload = SimpleUploadedFile("../../road.mp4", b"\x00\x00\x00\x18ftypisom", content_type="video/mp4")
        response = self.client.post("/api/upload-videos/", {"files": upload}, format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertRegex(response.data["uploaded_files"][0], r"^[a-f0-9]{32}$")
        user_root = Path(self.temp_dir.name) / "uploads" / str(self.user.pk)
        saved = list(user_root.glob("videos-*/*"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].name, f"{response.data['uploaded_files'][0]}.mp4")
        self.assertEqual(saved[0].parent.resolve().parent, user_root.resolve())

    def test_invalid_video_content_is_rejected(self):
        response = self.client.post(
            "/api/upload-videos/",
            {"files": SimpleUploadedFile("road.mp4", b"not a video", content_type="video/mp4")},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/upload-videos/",
            {"files": SimpleUploadedFile("road.mp4", b"\x00\x00\x00\x18ftypisom", content_type="video/mp4")},
            format="multipart",
        )
        self.assertIn(response.status_code, (401, 403))

    def test_client_supplied_paths_are_rejected(self):
        response = self.client.post(
            "/api/process-video/",
            {"video_path": "../../private.file", "gps_directory": "../../"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_non_admin_cannot_clean_uploads(self):
        response = self.client.post("/api/cleanup-uploads/", {}, format="json")
        self.assertIn(response.status_code, (401, 403))

    @patch("potholes.upload_views.call_command")
    def test_processing_uses_only_owned_uploaded_inputs(self, call_command):
        video = SimpleUploadedFile("road.mp4", b"\x00\x00\x00\x18ftypisom", content_type="video/mp4")
        video_result = self.client.post("/api/upload-videos/", {"files": video}, format="multipart")
        gps_data = b"$GPRMC,1\r\n$GPGGA,1\r\n"
        gps = SimpleUploadedFile("trace.git", gps_data, content_type="application/octet-stream")
        gps_result = self.client.post("/api/upload-gps/", {"files": gps}, format="multipart")
        self.assertEqual(video_result.status_code, 200, video_result.data)
        self.assertEqual(gps_result.status_code, 200, gps_result.data)
        response = self.client.post("/api/process-video/", {
            "video_id": video_result.data["uploaded_files"][0],
            "gps_batch_id": gps_result.data["upload_directory"],
            "distance_threshold": 2.5,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        kwargs = call_command.call_args.kwargs
        self.assertTrue(Path(kwargs["video_path"]).is_relative_to(Path(self.temp_dir.name).resolve()))
        self.assertTrue(Path(kwargs["gps_directory"]).is_relative_to(Path(self.temp_dir.name).resolve()))
        self.assertEqual(kwargs["owner_id"], self.user.pk)
        self.assertEqual(kwargs["source_identifier"], video_result.data["uploaded_files"][0])

    @patch("potholes.upload_views.call_command", side_effect=CommandError("processing failed"))
    def test_processing_failures_are_not_reported_as_success(self, call_command):
        video = SimpleUploadedFile("road.mp4", b"\x00\x00\x00\x18ftypisom", content_type="video/mp4")
        video_result = self.client.post("/api/upload-videos/", {"files": video}, format="multipart")
        gps = SimpleUploadedFile("trace.git", b"$GPRMC,1\r\n$GPGGA,1\r\n", content_type="application/octet-stream")
        gps_result = self.client.post("/api/upload-gps/", {"files": gps}, format="multipart")
        response = self.client.post("/api/process-video/", {
            "video_id": video_result.data["uploaded_files"][0],
            "gps_batch_id": gps_result.data["upload_directory"],
        }, format="json")
        self.assertEqual(response.status_code, 500)
        self.assertIn("processing failed", response.data["detail"].lower())
        call_command.assert_called_once()


class PotholeApiIntegrityTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="routiq-report-user",
            password="Safe-Test-Pass-8742!",
        )
        self.pothole = Pothole.objects.create(
            latitude="28.6139000",
            longitude="77.2090000",
            num_potholes=1,
            status="reported",
            severity="medium",
            description="Test record",
        )

    def test_anonymous_cannot_post_legacy_report(self):
        response = self.client.post(
            "/api/potholes/report/",
            {
                "latitude": 28.6139,
                "longitude": 77.2090,
                "num_potholes": 1,
                "confidence_score": 0.99,
            },
            format="json",
        )
        self.assertIn(response.status_code, (401, 403))

    @patch("potholes.report_view.validate_inference", return_value=None)
    def test_report_is_not_saved_when_validation_service_is_offline(self, validate):
        self.client.force_authenticate(self.user)
        from potholes.models import Pothole
        before = Pothole.objects.count()
        response = self.client.post(
            "/api/potholes/report/",
            {
                "latitude": 28.6139,
                "longitude": 77.2090,
                "num_potholes": 1,
                "confidence_score": 0.99,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(Pothole.objects.count(), before)
        validate.assert_called_once()

    def test_regular_user_cannot_modify_an_existing_legacy_pothole(self):
        self.client.force_authenticate(self.user)
        response = self.client.patch(
            f"/api/potholes/{self.pothole.pk}/",
            {"status": "fixed"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.pothole.refresh_from_db()
        self.assertEqual(self.pothole.status, "reported")

    def test_user_cannot_set_verified_status_or_model_provenance_when_creating(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/potholes/",
            {
                "latitude": 28.6,
                "longitude": 77.2,
                "num_potholes": 1,
                "status": "fixed",
                "severity": "critical",
                "source": "model_inference",
                "description": "Citizen report",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "reported")
        self.assertEqual(response.data["severity"], "medium")
        self.assertEqual(response.data["source"], "manual")
