"""Validate and persist owner-scoped per-detection dashcam records."""
from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .coordinates import parse_coordinate_pair
from .models import InspectionSession
from .services.observation_service import create_observation

REQUIRED_COLUMNS = {
    "source_id", "video_name", "frame_number", "date", "time", "latitude", "longitude",
    "gps_source", "class_id", "class_name", "confidence", "bbox",
}
SOURCE_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def read_per_detection_csv(path):
    """Read and validate the full CSV before any database writes occur."""
    records = []
    with Path(path).open("r", newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise ValueError("The per-detection file is missing required columns.")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("The per-detection file has duplicate column names.")
        for row_number, row in enumerate(reader, 2):
            if None in row:
                raise ValueError(f"Per-detection row {row_number} has extra values.")
            source_id = (row.get("source_id") or "").strip()
            if not SOURCE_ID_PATTERN.fullmatch(source_id):
                raise ValueError(f"Per-detection row {row_number} has an invalid source identifier.")
            video_name = row.get("video_name") or ""
            if not video_name or PurePosixPath(video_name).name != video_name or PureWindowsPath(video_name).name != video_name:
                raise ValueError(f"Per-detection row {row_number} must contain a video filename, not a path.")
            gps_source = row.get("gps_source") or ""
            if not gps_source or PurePosixPath(gps_source).name != gps_source or PureWindowsPath(gps_source).name != gps_source:
                raise ValueError(f"Per-detection row {row_number} has an invalid GPS source filename.")
            try:
                latitude, longitude = parse_coordinate_pair(row.get("latitude"), row.get("longitude"))
                confidence = float(row["confidence"])
                class_id = int(row["class_id"])
                frame_number = int(row["frame_number"])
                bbox = json.loads(row["bbox"])
                observed_at = datetime.strptime(
                    f"{row['date']} {row['time']}", "%m/%d/%Y %I:%M:%S %p"
                ).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Per-detection row {row_number} contains invalid coordinates, timestamp, confidence, or geometry.") from exc
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError(f"Per-detection row {row_number} confidence must be finite and from 0 to 1.")
            if class_id != 0 or row.get("class_name") != "pothole":
                raise ValueError(f"Per-detection row {row_number} has no verified RoutIQ class mapping.")
            if frame_number < 0:
                raise ValueError(f"Per-detection row {row_number} frame number must be non-negative.")
            if not isinstance(bbox, list) or len(bbox) != 4:
                raise ValueError(f"Per-detection row {row_number} must contain four bounding-box coordinates.")
            try:
                bbox = [float(value) for value in bbox]
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Per-detection row {row_number} contains invalid bounding-box coordinates.") from exc
            if any(not math.isfinite(value) or value < 0 for value in bbox) or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                raise ValueError(f"Per-detection row {row_number} contains invalid bounding-box geometry.")
            records.append({
                "source_id": source_id,
                "video_name": video_name,
                "frame_number": frame_number,
                "observed_at": observed_at,
                "latitude": latitude,
                "longitude": longitude,
                "gps_source": gps_source,
                "class_id": class_id,
                "damage_class": "pothole",
                "confidence": confidence,
                "bbox": bbox,
            })
    return records


@transaction.atomic
def ingest_per_detection_records(*, owner_id, source_identifier, records):
    """Persist validated records in a deterministic, owner-scoped session."""
    if not source_identifier or not re.fullmatch(r"[a-f0-9]{32}", str(source_identifier)):
        raise ValueError("A generated source video identifier is required.")
    owner = get_user_model().objects.get(pk=owner_id)
    session_key = uuid5(NAMESPACE_URL, f"routiq-dashcam:{owner.pk}:{source_identifier}")
    if not records:
        return {"session_id": None, "created": 0, "duplicates": 0}
    session, _ = InspectionSession.objects.get_or_create(
        session_key=session_key,
        defaults={
            "owner": owner,
            "title": f"Dashcam inspection: {records[0]['video_name']}",
            "source_kind": "dashcam",
            "status": "completed",
            "started_at": min(record["observed_at"] for record in records),
            "ended_at": max(record["observed_at"] for record in records),
            "metadata": {"source_identifier": source_identifier, "coordinate_source": "dashcam_gps"},
        },
    )
    if session.owner_id != owner.pk or session.source_kind != "dashcam":
        raise ValidationError("The generated dashcam session does not belong to the authenticated owner.")

    created = duplicates = 0
    for record in records:
        observation, was_created = create_observation(
            owner=owner,
            trusted_detector_output=True,
            validated_data={
                "session": session,
                "damage_class": record["damage_class"],
                "class_id": record["class_id"],
                "confidence": record["confidence"],
                "bbox": record["bbox"],
                "latitude": record["latitude"],
                "longitude": record["longitude"],
                "observed_at": record["observed_at"],
                "frame_number": record["frame_number"],
                "source_name": record["video_name"],
                "model_name": "legacy-dashcam-yolo",
                "idempotency_key": record["source_id"],
                "metadata": {
                    "coordinate_source": "dashcam_gps",
                    "gps_source_file": record["gps_source"],
                    "source_identifier": source_identifier,
                },
            },
        )
        created += int(was_created)
        duplicates += int(not was_created)
    return {"session_id": session.pk, "created": created, "duplicates": duplicates}
