"""Reproducible evaluation for labelled temporal observation pairs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from .matching import haversine_distance_m
from .quality_assessment import observation_quality
from .status_assessment import compare_observations

REQUIRED_COLUMNS = {
    "label", "damage_class_a", "damage_class_b", "latitude_a", "longitude_a",
    "latitude_b", "longitude_b", "observed_at_a", "observed_at_b",
    "confidence_a", "confidence_b", "gps_accuracy_m_a", "gps_accuracy_m_b",
    "image_width_a", "image_height_a", "image_width_b", "image_height_b",
}


def _timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamps must include a timezone offset")
    return parsed


def _number(value):
    if value in (None, ""):
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("numeric values must be finite")
    return result


def _validate_row(row, number):
    missing = REQUIRED_COLUMNS.difference(row)
    if missing:
        raise ValueError(f"Row {number} is missing required columns: {', '.join(sorted(missing))}")
    label = row.get("label")
    if label not in {"same_damage", "different_damage"}:
        raise ValueError(f"Row {number} label must be same_damage or different_damage.")
    for suffix in ("a", "b"):
        damage_class = row.get(f"damage_class_{suffix}")
        if not isinstance(damage_class, str) or not damage_class.strip():
            raise ValueError(f"Row {number} damage_class_{suffix} is required.")
        try:
            _timestamp(row.get(f"observed_at_{suffix}"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Row {number} observed_at_{suffix} must be an ISO 8601 timestamp with a timezone.") from exc

        confidence = _number(row.get(f"confidence_{suffix}"))
        if confidence is None or not 0 <= confidence <= 1:
            raise ValueError(f"Row {number} confidence_{suffix} must be from 0 to 1.")
        accuracy = _number(row.get(f"gps_accuracy_m_{suffix}"))
        if accuracy is not None and accuracy < 0:
            raise ValueError(f"Row {number} gps_accuracy_m_{suffix} must be non-negative or blank.")

        latitude = _number(row.get(f"latitude_{suffix}"))
        longitude = _number(row.get(f"longitude_{suffix}"))
        if (latitude is None) != (longitude is None):
            raise ValueError(f"Row {number} coordinates for observation {suffix} must both be present or both be blank.")
        if latitude is not None and not -90 <= latitude <= 90:
            raise ValueError(f"Row {number} latitude_{suffix} must be from -90 to 90.")
        if longitude is not None and not -180 <= longitude <= 180:
            raise ValueError(f"Row {number} longitude_{suffix} must be from -180 to 180.")

        dimensions = [_number(row.get(f"image_{dimension}_{suffix}")) for dimension in ("width", "height")]
        if (dimensions[0] is None) != (dimensions[1] is None):
            raise ValueError(f"Row {number} image width and height for observation {suffix} must both be present or both be blank.")
        if any(value is not None and (value < 1 or not value.is_integer()) for value in dimensions):
            raise ValueError(f"Row {number} image dimensions for observation {suffix} must be positive integers or blank.")


def _observation(row, suffix):
    return SimpleNamespace(
        damage_class=row[f"damage_class_{suffix}"],
        latitude=_number(row[f"latitude_{suffix}"]),
        longitude=_number(row[f"longitude_{suffix}"]),
        observed_at=_timestamp(row[f"observed_at_{suffix}"]),
        confidence=_number(row[f"confidence_{suffix}"]),
        gps_accuracy_m=_number(row[f"gps_accuracy_m_{suffix}"]),
        metadata={
            "image_width": _number(row[f"image_width_{suffix}"]),
            "image_height": _number(row[f"image_height_{suffix}"]),
        },
    )


def _metrics(rows, decisions):
    positive_labels = sum(row["label"] == "same_damage" for row in rows)
    negative_labels = len(rows) - positive_labels
    predicted_matches = [index for index, result in enumerate(decisions) if result == "same_damage"]
    true_matches = sum(rows[index]["label"] == "same_damage" for index in predicted_matches)
    false_matches = len(predicted_matches) - true_matches
    abstentions = sum(result == "uncertain" for result in decisions)
    decided = len(rows) - abstentions
    errors = sum(
        decisions[index] != "uncertain" and decisions[index] != row["label"]
        for index, row in enumerate(rows)
    )
    return {
        "pairs": len(rows),
        "candidate_match_precision": true_matches / len(predicted_matches) if predicted_matches else None,
        "candidate_match_recall": true_matches / positive_labels if positive_labels else None,
        "false_match_rate": false_matches / negative_labels if negative_labels else None,
        "abstention_rate": abstentions / len(rows) if rows else None,
        "coverage": decided / len(rows) if rows else None,
        "error_rate_non_abstained": errors / decided if decided else None,
    }


def evaluate_rows(rows, *, distance_threshold_m=15.0):
    """Evaluate quality-aware decisions and a class-plus-distance baseline."""
    if not 3.0 <= float(distance_threshold_m) <= 100.0:
        raise ValueError("distance_threshold_m must be from 3 to 100 meters.")
    normalized = []
    proposed = []
    baseline = []
    strata = {"high": [], "medium": [], "low": []}
    for number, source in enumerate(rows, 1):
        row = dict(source)
        if None in row:
            raise ValueError(f"Row {number} has more values than the header.")
        _validate_row(row, number)
        first, second = _observation(row, "a"), _observation(row, "b")
        comparison = compare_observations(first, second, distance_threshold_m)
        proposed.append(comparison["decision"])

        valid_coordinates = all(value is not None for value in (
            first.latitude, first.longitude, second.latitude, second.longitude
        ))
        if valid_coordinates:
            distance = haversine_distance_m(
                first.latitude, first.longitude, second.latitude, second.longitude
            )
            baseline.append(
                "same_damage" if first.damage_class == second.damage_class and distance <= distance_threshold_m
                else "different_damage"
            )
        else:
            baseline.append("uncertain")

        quality = min(observation_quality(first)["score"], observation_quality(second)["score"])
        stratum = "high" if quality >= 0.75 else "medium" if quality >= 0.50 else "low"
        strata[stratum].append((row, comparison["decision"]))
        normalized.append(row)

    stratified = {
        name: _metrics([item[0] for item in items], [item[1] for item in items])
        for name, items in strata.items() if items
    }
    return {
        "schema_version": 1,
        "distance_threshold_m": float(distance_threshold_m),
        "quality_aware_rule": _metrics(normalized, proposed),
        "baseline_class_and_distance_only": _metrics(normalized, baseline),
        "quality_strata": stratified,
        "interpretation": "Heuristic decisions and dataset metrics are not calibrated probabilities or evidence of repair.",
    }


def evaluate_csv(path, *, distance_threshold_m=15.0):
    """Evaluate a labelled CSV and include a stable digest of the input bytes."""
    source = Path(path)
    raw = source.read_bytes()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ValueError("The evaluation CSV must include a header row.")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("The evaluation CSV must not contain duplicate column names.")
    missing = REQUIRED_COLUMNS.difference(reader.fieldnames)
    if missing:
        raise ValueError(f"Evaluation CSV is missing columns: {', '.join(sorted(missing))}")
    result = evaluate_rows(reader, distance_threshold_m=distance_threshold_m)
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    result["input_file"] = source.name
    return result


def validate_csv(path):
    """Validate labelled rows and return a digest without calculating metrics."""
    source = Path(path)
    raw = source.read_bytes()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ValueError("The evaluation CSV must include a header row.")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("The evaluation CSV must not contain duplicate column names.")
    missing = REQUIRED_COLUMNS.difference(reader.fieldnames)
    if missing:
        raise ValueError(f"Evaluation CSV is missing columns: {', '.join(sorted(missing))}")
    count = 0
    for count, row in enumerate(reader, 1):
        if None in row:
            raise ValueError(f"Row {count} has more values than the header.")
        _validate_row(row, count)
    return {"valid": True, "rows": count, "input_sha256": hashlib.sha256(raw).hexdigest(), "input_file": source.name}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate RoutIQ temporal decisions against labelled observation pairs.")
    parser.add_argument("input_csv", help="Path to the labelled evaluation CSV")
    parser.add_argument("--distance-threshold-m", type=float, default=15.0)
    parser.add_argument("--validate-only", action="store_true", help="Validate the CSV schema and values without reporting evaluation metrics")
    args = parser.parse_args(argv)
    try:
        result = validate_csv(args.input_csv) if args.validate_only else evaluate_csv(args.input_csv, distance_threshold_m=args.distance_threshold_m)
        print(json.dumps(result, indent=2))
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
