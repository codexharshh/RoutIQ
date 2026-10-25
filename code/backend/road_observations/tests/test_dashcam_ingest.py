import csv
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from dashcam_processor.per_detection import write_per_detection_rows
from road_observations.dashcam_ingest import (
    REQUIRED_COLUMNS,
    ingest_per_detection_records,
    read_per_detection_csv,
)
from road_observations.models import DamageObservation, InspectionSession


def detection_csv_row(**overrides):
    return {
        "source_id": "a" * 64,
        "video_name": "upload-id.mp4",
        "frame_number": "24",
        "date": "01/02/2026",
        "time": "08:30:00 AM",
        "latitude": "28.6139",
        "longitude": "77.2090",
        "gps_source": "trace-id.git",
        "class_id": "0",
        "class_name": "pothole",
        "confidence": "0.87",
        "bbox": "[10,20,50,60]",
        **overrides,
    }


class PerDetectionExportTests(unittest.TestCase):
    def test_processor_export_preserves_actual_per_box_fields_and_stable_identity(self):
        writer_buffer = StringIO()
        writer = csv.DictWriter(writer_buffer, fieldnames=sorted({
            "source_id", "video_name", "frame_number", "date", "time", "latitude", "longitude",
            "gps_source", "class_id", "class_name", "confidence", "bbox",
        }))
        writer.writeheader()
        count = write_per_detection_rows(
            writer,
            source_identifier="b" * 32,
            video_name="upload-id.mp4",
            frame_number=24,
            date="01/02/2026",
            time="08:30:00 AM",
            gps_entry={"lat": 28.6139, "lon": 77.2090, "source_file": "trace-id.git"},
            detections=[{"class": 0, "confidence": 0.87, "bbox": (10, 20, 40, 40)}],
        )
        first_output = writer_buffer.getvalue()
        self.assertEqual(count, 1)
        self.assertIn("0.87", first_output)
        self.assertIn("[10.0,20.0,50.0,60.0]", first_output)
        exported = next(csv.DictReader(StringIO(first_output)))
        self.assertEqual(len(exported["source_id"]), 64)

    def test_processor_export_rejects_invalid_gps_and_unmapped_classes(self):
        writer = Mock()
        for gps, detections in (
            ({"lat": 95, "lon": 77, "source_file": "trace.git"}, [{"class": 0, "confidence": 0.8, "bbox": (1, 1, 5, 5)}]),
            ({"lat": 28, "lon": 77, "source_file": "trace.git"}, [{"class": 1, "confidence": 0.8, "bbox": (1, 1, 5, 5)}]),
        ):
            with self.subTest(gps=gps, detections=detections), self.assertRaises(ValueError):
                write_per_detection_rows(
                    writer, source_identifier="b" * 32, video_name="upload.mp4", frame_number=1,
                    date="01/02/2026", time="08:30:00 AM", gps_entry=gps, detections=detections,
                )
        writer.writerows.assert_not_called()


class DashcamObservationIngestTests(APITestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="dashcam-observation-owner", password="test-pass")
        self.other_owner = get_user_model().objects.create_user(username="dashcam-observation-other", password="test-pass")
        self.source_identifier = "c" * 32

    def _read_rows(self, row):
        with tempfile.TemporaryDirectory(prefix="routiq-dashcam-csv-") as directory:
            path = Path(directory) / "per_detection.csv"
            with path.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=sorted(REQUIRED_COLUMNS))
                writer.writeheader()
                writer.writerow(row)
            return read_per_detection_csv(path)

    def test_valid_per_detection_rows_are_owner_scoped_and_mappable(self):
        records = self._read_rows(detection_csv_row())
        result = ingest_per_detection_records(
            owner_id=self.owner.pk, source_identifier=self.source_identifier, records=records
        )
        self.assertEqual(result["created"], 1)
        observation = DamageObservation.objects.select_related("session", "instance").get()
        self.assertEqual(observation.session.owner_id, self.owner.pk)
        self.assertEqual(observation.session.source_kind, "dashcam")
        self.assertEqual(observation.damage_class, "pothole")
        self.assertEqual(observation.class_id, 0)
        self.assertAlmostEqual(observation.confidence, 0.87)
        self.assertEqual(observation.bbox, [10.0, 20.0, 50.0, 60.0])
        self.assertEqual(observation.metadata["coordinate_source"], "dashcam_gps")
        self.assertEqual(observation.metadata["gps_source_file"], "trace-id.git")
        self.client.force_authenticate(self.owner)
        response = self.client.get(reverse("road_observations:map"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["coordinate_source"], "dashcam_gps")
        self.assertEqual(response.data[0]["latitude"], 28.6139)

    def test_reprocessing_the_same_source_skips_duplicate_observations(self):
        records = self._read_rows(detection_csv_row())
        first = ingest_per_detection_records(owner_id=self.owner.pk, source_identifier=self.source_identifier, records=records)
        second = ingest_per_detection_records(owner_id=self.owner.pk, source_identifier=self.source_identifier, records=records)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(DamageObservation.objects.count(), 1)
        self.assertEqual(InspectionSession.objects.count(), 1)

    def test_invalid_or_missing_gps_is_rejected_before_persistence(self):
        for row in (
            detection_csv_row(latitude="95"),
            detection_csv_row(latitude="", longitude=""),
            detection_csv_row(latitude="28.6", longitude=""),
        ):
            with self.subTest(row=row), self.assertRaises(ValueError):
                records = self._read_rows(row)
                ingest_per_detection_records(owner_id=self.owner.pk, source_identifier=self.source_identifier, records=records)
        self.assertEqual(DamageObservation.objects.count(), 0)
        self.assertEqual(InspectionSession.objects.count(), 0)

    def test_same_source_identifier_does_not_cross_user_boundaries(self):
        records = self._read_rows(detection_csv_row())
        ingest_per_detection_records(owner_id=self.owner.pk, source_identifier=self.source_identifier, records=records)
        ingest_per_detection_records(owner_id=self.other_owner.pk, source_identifier=self.source_identifier, records=records)
        self.assertEqual(DamageObservation.objects.count(), 2)
        self.client.force_authenticate(self.owner)
        response = self.client.get(reverse("road_observations:map"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(DamageObservation.objects.get(session__owner=self.owner).session.owner_id, self.owner.pk)

    def test_invalid_confidence_and_bounding_boxes_are_rejected(self):
        for row in (detection_csv_row(confidence="NaN"), detection_csv_row(bbox="[10,20,5,60]")):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self._read_rows(row)
        self.assertEqual(DamageObservation.objects.count(), 0)

    def test_source_identifier_is_required_for_idempotency(self):
        records = self._read_rows(detection_csv_row())
        with self.assertRaises(ValueError):
            ingest_per_detection_records(owner_id=self.owner.pk, source_identifier="invalid", records=records)
        self.assertEqual(DamageObservation.objects.count(), 0)


if __name__ == "__main__":
    unittest.main()
