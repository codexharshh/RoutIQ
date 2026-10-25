"""Serialize verified legacy detector outputs into per-detection CSV rows."""
import csv
import hashlib
import json
import math


PER_DETECTION_FIELDS = [
    "source_id", "video_name", "frame_number", "date", "time", "latitude", "longitude",
    "gps_source", "class_id", "class_name", "confidence", "bbox",
]


def write_per_detection_rows(csv_writer, *, source_identifier, video_name, frame_number, date, time, gps_entry, detections):
    """Write validated per-box rows with the matched frame GPS and time provenance."""
    latitude, longitude = float(gps_entry["lat"]), float(gps_entry["lon"])
    gps_source = str(gps_entry.get("source_file", "")).strip()
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        raise ValueError("Matched GPS coordinates must be finite.")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Matched GPS coordinates are outside WGS-84 bounds.")
    if not gps_source or gps_source == "Unknown":
        raise ValueError("Matched GPS source file is unavailable.")

    rows = []
    for detection_index, detection in enumerate(detections):
        class_id = int(detection["class"])
        if class_id != 0:
            raise ValueError("Legacy detector class ID has no verified RoutIQ class mapping.")
        confidence = float(detection["confidence"])
        x1, y1, width, height = map(float, detection["bbox"])
        bbox = [x1, y1, x1 + width, y1 + height]
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Legacy detector confidence is invalid.")
        if any(not math.isfinite(value) or value < 0 for value in bbox) or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("Legacy detector bounding box is invalid.")
        identity = f"{source_identifier}:{video_name}:{frame_number}:{detection_index}"
        rows.append({
            "source_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            "video_name": video_name,
            "frame_number": frame_number,
            "date": date,
            "time": time,
            "latitude": latitude,
            "longitude": longitude,
            "gps_source": gps_source,
            "class_id": class_id,
            "class_name": "pothole",
            "confidence": confidence,
            "bbox": json.dumps(bbox, separators=(",", ":")),
        })
    csv_writer.writerows(rows)
    return len(rows)
