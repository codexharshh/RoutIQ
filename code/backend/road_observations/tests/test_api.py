from io import BytesIO
from pathlib import Path
import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.conf import settings
from django.urls import reverse
from PIL import Image
from rest_framework.test import APITestCase
from rest_framework import status
from django.utils import timezone

from road_damage.schemas import Detection
from road_damage.detector import MockDetector
from road_observations.models import DamageObservation, InspectionSession


def png_upload():
    buffer = BytesIO()
    Image.new("RGB", (80, 60), (80, 80, 80)).save(buffer, format="PNG")
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile("road.png", buffer.getvalue(), content_type="image/png")


class RoutIQDetectionApiTests(APITestCase):
    def setUp(self):
        self.evidence_directory = tempfile.TemporaryDirectory(prefix="routiq-test-evidence-")
        self.evidence_storage = InspectionSession._meta.get_field("image_evidence").storage
        self.original_storage_location = self.evidence_storage._location
        self.evidence_storage._location = self.evidence_directory.name
        User = get_user_model()
        self.user = User.objects.create_user(username="routiq-test-user", password="test-pass")
        self.client.force_authenticate(user=self.user)
        self.url = reverse("road_observations:detect-image")

    def tearDown(self):
        self.evidence_storage._location = self.original_storage_location
        self.evidence_directory.cleanup()
        super().tearDown()

    def test_image_detection_saves_observations(self):
        sample = Detection(
            class_id=3,
            class_name="pothole",
            confidence=0.91,
            bbox=(10, 12, 40, 45),
            model_name="test-model",
            model_version="test-version",
        )
        with patch("road_observations.views.get_detector",
                   return_value=MockDetector([sample])):
            response = self.client.post(
                self.url,
                {"image": png_upload(), "latitude": "28.6139", "longitude": "77.2090"},
                format="multipart",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(DamageObservation.objects.count(), 1)
        self.assertEqual(InspectionSession.objects.count(), 1)
        saved = DamageObservation.objects.select_related("instance").get()
        self.assertEqual(saved.damage_class, "pothole")
        self.assertEqual(saved.class_id, 3)
        self.assertAlmostEqual(saved.confidence, 0.91)
        self.assertEqual(str(saved.latitude), "28.6139000")
        self.assertEqual(saved.instance.current_status, "unknown")
        session = InspectionSession.objects.get()
        self.assertEqual(session.owner_id, self.user.pk)
        self.assertEqual(saved.metadata["image_width"], 80)
        self.assertEqual(saved.metadata["image_height"], 60)
        self.assertTrue(session.image_evidence.name.startswith("sessions/"))
        self.assertTrue(session.evidence_expires_at)
        with self.assertRaises(ValueError):
            _ = session.image_evidence.url
        self.assertFalse(Path(session.image_evidence.path).is_relative_to(Path(settings.MEDIA_ROOT).resolve()))

        sessions_response = self.client.get(reverse("road_observations:sessions"))
        self.assertEqual(sessions_response.status_code, status.HTTP_200_OK)
        self.assertTrue(sessions_response.data[0]["evidence_available"])
        self.assertNotIn("image_evidence", sessions_response.data[0])

    def test_retained_evidence_is_owner_scoped_and_download_only(self):
        sample = Detection(
            class_id=3, class_name="pothole", confidence=0.91,
            bbox=(10, 12, 40, 45), model_name="test-model", model_version="test-version",
        )
        with patch("road_observations.views.get_detector", return_value=MockDetector([sample])):
            self.client.post(self.url, {"image": png_upload()}, format="multipart")
        session = InspectionSession.objects.get()
        evidence_url = reverse("road_observations:session-evidence", args=[session.pk])
        response = self.client.get(evidence_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", response["Cache-Control"])

        other = get_user_model().objects.create_user(username="evidence-non-owner", password="test-pass")
        self.client.force_authenticate(user=other)
        self.assertEqual(self.client.get(evidence_url).status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_retained_evidence_returns_gone_instead_of_server_error(self):
        session = InspectionSession.objects.create(owner=self.user)
        session.image_evidence.save("missing.png", ContentFile(b"old evidence"), save=True)
        self.evidence_storage.delete(session.image_evidence.name)

        response = self.client.get(
            reverse("road_observations:session-evidence", args=[session.pk])
        )

        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertIn("Re-upload this image", response.data["detail"])

    def test_owner_can_delete_evidence_without_deleting_observation(self):
        sample = Detection(
            class_id=3, class_name="pothole", confidence=0.91,
            bbox=(10, 12, 40, 45), model_name="test-model", model_version="test-version",
        )
        with patch("road_observations.views.get_detector", return_value=MockDetector([sample])):
            self.client.post(self.url, {"image": png_upload()}, format="multipart")
        session = InspectionSession.objects.get()
        response = self.client.delete(reverse("road_observations:session-evidence", args=[session.pk]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        session.refresh_from_db()
        self.assertFalse(session.image_evidence)
        self.assertIsNone(session.evidence_expires_at)
        self.assertEqual(DamageObservation.objects.count(), 1)

    def test_invalid_file_extension_is_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = self.client.post(
            self.url,
            {"image": SimpleUploadedFile("bad.exe", b"not-image")},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_image_bytes_are_rejected_before_inference(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        with patch("road_observations.views.get_detector") as detector:
            response = self.client.post(
                self.url,
                {"image": SimpleUploadedFile("bad.png", b"not-an-image", content_type="image/png")},
                format="multipart",
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        detector.assert_not_called()
        self.assertEqual(InspectionSession.objects.count(), 0)

    def test_expired_evidence_is_unavailable_and_purge_is_explicit(self):
        sample = Detection(
            class_id=3, class_name="pothole", confidence=0.91,
            bbox=(10, 12, 40, 45), model_name="test-model", model_version="test-version",
        )
        with patch("road_observations.views.get_detector", return_value=MockDetector([sample])):
            self.client.post(self.url, {"image": png_upload()}, format="multipart")
        session = InspectionSession.objects.get()
        stored_name = session.image_evidence.name
        evidence_path = session.image_evidence.path
        session.evidence_expires_at = timezone.now() - timedelta(seconds=1)
        session.save(update_fields=["evidence_expires_at"])
        url = reverse("road_observations:session-evidence", args=[session.pk])
        self.assertEqual(self.client.get(url).status_code, 410)

        call_command("purge_expired_evidence")
        session.refresh_from_db()
        self.assertEqual(session.image_evidence.name, stored_name)
        self.assertTrue(Path(evidence_path).is_file())

        call_command("purge_expired_evidence", execute=True)
        session.refresh_from_db()
        self.assertFalse(session.image_evidence)
        self.assertFalse(Path(evidence_path).exists())
        self.assertEqual(DamageObservation.objects.count(), 1)

    def test_evidence_without_explicit_expiry_uses_configured_retention(self):
        sample = Detection(
            class_id=3, class_name="pothole", confidence=0.91,
            bbox=(10, 12, 40, 45), model_name="test-model", model_version="test-version",
        )
        with patch("road_observations.views.get_detector", return_value=MockDetector([sample])):
            self.client.post(self.url, {"image": png_upload()}, format="multipart")
        session = InspectionSession.objects.get()
        evidence_path = Path(session.image_evidence.path)
        InspectionSession.objects.filter(pk=session.pk).update(
            evidence_expires_at=None,
            created_at=timezone.now() - timedelta(days=settings.ROUTIQ_EVIDENCE_RETENTION_DAYS + 1),
        )
        url = reverse("road_observations:session-evidence", args=[session.pk])
        self.assertEqual(self.client.get(url).status_code, status.HTTP_410_GONE)
        call_command("purge_expired_evidence", execute=True)
        session.refresh_from_db()
        self.assertFalse(session.image_evidence)
        self.assertFalse(evidence_path.exists())

    def test_non_finite_coordinates_are_rejected_before_inference(self):
        with patch("road_observations.views.get_detector") as detector:
            response = self.client.post(
                self.url,
                {"image": png_upload(), "latitude": "NaN", "longitude": "77.2090"},
                format="multipart",
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        detector.assert_not_called()
        self.assertEqual(DamageObservation.objects.count(), 0)
        self.assertEqual(InspectionSession.objects.count(), 0)

    def test_gps_source_and_accuracy_are_preserved(self):
        sample = Detection(
            class_id=3, class_name="pothole", confidence=0.91,
            bbox=(10, 12, 40, 45), model_name="test-model", model_version="test-version",
        )
        with patch("road_observations.views.get_detector", return_value=MockDetector([sample])):
            response = self.client.post(
                self.url,
                {"image": png_upload(), "latitude": "28.6139", "longitude": "77.2090",
                 "coordinate_source": "device_current", "gps_accuracy_m": "4.5"},
                format="multipart",
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        saved = DamageObservation.objects.get()
        self.assertEqual(saved.metadata["coordinate_source"], "device_current")
        self.assertAlmostEqual(saved.gps_accuracy_m, 4.5)

    def test_upload_to_map_feed_and_location_update_end_to_end(self):
        from unittest.mock import Mock

        vision_response = Mock(ok=True, status_code=200)
        vision_response.json.return_value = {
            "count": 1,
            "detections": [{
                "class_id": 3, "class_name": "pothole", "confidence": 0.91,
                "bbox": [10, 12, 40, 45], "model_name": "test-model",
                "model_version": "test-version",
            }],
        }
        with patch("road_observations.vision_client.requests.post", return_value=vision_response) as vision_post:
            located_response = self.client.post(
                self.url,
                {"image": png_upload(), "latitude": "28.6139", "longitude": "77.2090",
                 "coordinate_source": "manual"},
                format="multipart",
            )
            self.assertEqual(located_response.status_code, status.HTTP_201_CREATED, located_response.data)
            self.assertEqual(located_response.data["results"][0]["damage_class"], "pothole")
            self.assertTrue(vision_post.called)
            located_map = self.client.get(reverse("road_observations:map"))
            self.assertEqual(len(located_map.data), 1)
            self.assertEqual(located_map.data[0]["latitude"], 28.6139)
            self.assertEqual(located_map.data[0]["longitude"], 77.209)

            unmapped_response = self.client.post(
                self.url, {"image": png_upload()}, format="multipart"
            )
            self.assertEqual(unmapped_response.status_code, status.HTTP_201_CREATED)
            unmapped = DamageObservation.objects.get(pk=unmapped_response.data["results"][0]["id"])
            map_before_update = self.client.get(reverse("road_observations:map"))
            self.assertEqual(len(map_before_update.data), 1)

            update = self.client.patch(
                reverse("road_observations:update-location", args=[unmapped.pk]),
                {"latitude": "35.6895", "longitude": "139.6917", "coordinate_source": "manual"},
                format="json",
            )
            self.assertEqual(update.status_code, status.HTTP_200_OK, update.data)
            map_after_update = self.client.get(reverse("road_observations:map"))
            self.assertEqual(len(map_after_update.data), 2)
            marker = next(item for item in map_after_update.data if item["id"] == unmapped.pk)
            self.assertEqual(marker["latitude"], 35.6895)
            self.assertEqual(marker["longitude"], 139.6917)
            self.assertEqual(marker["coordinate_source"], "manual")

    def test_disabled_or_failed_inference_does_not_create_records(self):
        with patch("road_observations.views.get_detector", side_effect=RuntimeError("service unavailable")):
            response = self.client.post(self.url, {"image": png_upload()}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(InspectionSession.objects.count(), 0)
        self.assertEqual(DamageObservation.objects.count(), 0)

    def test_photo_exif_source_requires_metadata_not_client_coordinates(self):
        response = self.client.post(
            self.url,
            {"image": png_upload(), "latitude": "28.6139", "longitude": "77.2090",
             "coordinate_source": "photo_exif"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(InspectionSession.objects.count(), 0)

    def test_photo_exif_coordinates_are_extracted_and_recorded_with_provenance(self):
        sample = Detection(
            class_id=3, class_name="pothole", confidence=0.91,
            bbox=(10, 12, 40, 45), model_name="test-model", model_version="test-version",
        )
        with patch("road_observations.views.extract_photo_gps",
                   return_value=(Decimal("28.6139"), Decimal("77.2090"), 5.0)), \
                patch("road_observations.views.get_detector", return_value=MockDetector([sample])):
            response = self.client.post(
                self.url,
                {"image": png_upload(), "coordinate_source": "photo_exif"},
                format="multipart",
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        saved = DamageObservation.objects.get()
        self.assertEqual(saved.metadata["coordinate_source"], "photo_exif")
        self.assertEqual(str(saved.latitude), "28.6139000")
        self.assertAlmostEqual(saved.gps_accuracy_m, 5.0)

    def test_private_storage_rejects_path_traversal(self):
        with self.assertRaises(SuspiciousFileOperation):
            self.evidence_storage.save("../outside.png", ContentFile(b"private"))

    def test_detection_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {"image": png_upload()}, format="multipart")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED,
                                            status.HTTP_403_FORBIDDEN))


class RoutIQMapFeedTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="routiq-map-owner", password="test-pass")
        self.other_user = User.objects.create_user(username="routiq-map-other", password="test-pass")

    def test_detector_readiness_is_authenticated_and_sanitized(self):
        url = reverse("road_observations:detector-status")
        self.assertIn(self.client.get(url).status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.client.force_authenticate(user=self.user)
        with patch("road_observations.views.get_detector") as detector:
            detector.return_value.detector_status.return_value = {
                "status": "ready_to_test", "labels": "compatible", "inference_tested": False,
            }
            response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ready_to_test")
        self.assertNotIn("weights_path", response.data)

    def test_detector_readiness_reports_missing_weights_without_claiming_inference(self):
        self.client.force_authenticate(user=self.user)
        with patch("road_observations.views.get_detector") as detector:
            detector.return_value.detector_status.return_value = {
                "status": "weights_not_found", "labels": "not_checked", "inference_tested": False,
            }
            response = self.client.get(reverse("road_observations:detector-status"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "weights_not_found")
        self.assertFalse(response.data["inference_tested"])

    def test_detector_readiness_reports_service_unavailable_without_details(self):
        from road_observations.vision_client import VisionServiceUnavailable
        self.client.force_authenticate(user=self.user)
        with patch("road_observations.views.get_detector") as detector:
            detector.return_value.detector_status.side_effect = VisionServiceUnavailable("private host and path")
            response = self.client.get(reverse("road_observations:detector-status"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "vision_unavailable")
        self.assertNotIn("private", str(response.data))

    def test_detector_readiness_distinguishes_timeout_and_malformed_report(self):
        from road_observations.vision_client import VisionReadinessError, VisionServiceTimeout
        self.client.force_authenticate(user=self.user)
        url = reverse("road_observations:detector-status")
        for error, expected in (
            (VisionServiceTimeout("private timeout details"), "vision_timeout"),
            (VisionReadinessError("private response details"), "invalid_readiness_response"),
        ):
            with self.subTest(expected=expected), patch("road_observations.views.get_detector") as detector:
                detector.return_value.detector_status.side_effect = error
                response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data, {
                "status": expected, "labels": "not_checked", "inference_tested": False,
            })
            self.assertNotIn("private", str(response.data))

    def _create_observation(self, owner, name):
        from road_observations.models import DamageInstance
        session = InspectionSession.objects.create(owner=owner, title=f"Map test {name}")
        instance = DamageInstance.objects.create(
            created_by=owner,
            damage_class="pothole",
            latitude="28.6139000",
            longitude="77.2090000",
        )
        return DamageObservation.objects.create(
            session=session,
            instance=instance,
            damage_class="pothole",
            confidence=0.88,
            latitude="28.6139000",
            longitude="77.2090000",
        )

    def test_map_feed_requires_authentication(self):
        response = self.client.get("/api/v1/road-observations/map/")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_map_feed_returns_only_current_users_gps_observations(self):
        own = self._create_observation(self.user, "own")
        self._create_observation(self.other_user, "other")
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/road-observations/map/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], own.id)
        self.assertEqual(response.data[0]["damage_class"], "pothole")
        self.assertEqual(response.data[0]["latitude"], 28.6139)

    def test_map_feed_excludes_out_of_range_saved_coordinates(self):
        self._create_observation(self.user, "valid")
        invalid = self._create_observation(self.user, "invalid")
        DamageObservation.objects.filter(pk=invalid.pk).update(latitude="95", longitude="190")
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/road-observations/map/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)


class RoadDamageStatsTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="routiq-stats-owner", password="test-pass")
        self.other_user = User.objects.create_user(username="routiq-stats-other", password="test-pass")
        self.url = "/api/v1/road-observations/stats/"

    def _create(self, owner, name, damage_class="pothole", mapped=True):
        from road_observations.models import DamageInstance
        session = InspectionSession.objects.create(owner=owner, title=f"Stats {name}")
        instance = DamageInstance.objects.create(
            created_by=owner, damage_class=damage_class, current_status="unknown",
            latitude="28.6139000" if mapped else None,
            longitude="77.2090000" if mapped else None,
        )
        return DamageObservation.objects.create(
            session=session, instance=instance, damage_class=damage_class, confidence=0.8,
            latitude="28.6139000" if mapped else None,
            longitude="77.2090000" if mapped else None,
        )

    def test_stats_require_authentication(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_stats_are_scoped_to_current_user(self):
        self._create(self.user, "own-pothole", "pothole", True)
        self._create(self.user, "own-crack", "longitudinal_crack", False)
        self._create(self.other_user, "other-user", "pothole", True)
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["total_observations"], 2)
        self.assertEqual(response.data["mapped_observations"], 1)
        self.assertEqual(response.data["sessions"], 2)
        self.assertEqual(response.data["by_class"]["pothole"], 1)
        self.assertEqual(response.data["by_class"]["longitudinal_crack"], 1)
