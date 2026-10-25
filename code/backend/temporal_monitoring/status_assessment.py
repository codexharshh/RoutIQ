"""Quality-aware abstaining comparison for repeat-pass road observations.

The rule only compares two positive detections. It never infers that a road is repaired
from the absence of a later detection; its output is a candidate for review, not proof.
"""
from __future__ import annotations
from datetime import timezone as datetime_timezone

from .matching import haversine_distance_m
from .quality_assessment import observation_quality

MIN_TEMPORAL_GAP_HOURS = 1.0 / 6.0  # 10 minutes: avoid matching frames from one pass.
MIN_QUALITY_SCORE = 0.50


def _time_delta_hours(a, b):
    first = getattr(a, "observed_at", None)
    second = getattr(b, "observed_at", None)
    if first is None or second is None:
        return None
    # Django model datetimes are aware. Normalize naive test/import values as UTC.
    if first.tzinfo is None:
        first = first.replace(tzinfo=datetime_timezone.utc)
    if second.tzinfo is None:
        second = second.replace(tzinfo=datetime_timezone.utc)
    return abs((second - first).total_seconds()) / 3600.0


def compare_observations(a, b, distance_threshold_m=15.0):
    threshold = float(distance_threshold_m)
    if not 3.0 <= threshold <= 100.0:
        raise ValueError("distance_threshold_m must be from 3 to 100 meters.")

    quality_a = observation_quality(a)
    quality_b = observation_quality(b)
    reasons = []
    lat_a, lon_a = getattr(a, "latitude", None), getattr(a, "longitude", None)
    lat_b, lon_b = getattr(b, "latitude", None), getattr(b, "longitude", None)
    gap = _time_delta_hours(a, b)

    if None in (lat_a, lon_a, lat_b, lon_b):
        reasons.append("Both observations need photo GPS coordinates before spatial comparison.")
        return {
            "decision": "uncertain", "score": None, "distance_m": None,
            "temporal_gap_hours": round(gap, 3) if gap is not None else None,
            "quality_a": quality_a, "quality_b": quality_b, "reasons": reasons,
            "abstained": True, "repair_verification": "not_inferred",
        }

    try:
        distance = haversine_distance_m(lat_a, lon_a, lat_b, lon_b)
    except (TypeError, ValueError, OverflowError):
        reasons.append("Stored GPS coordinates are invalid; spatial comparison was not performed.")
        return {
            "decision": "uncertain", "score": None, "distance_m": None,
            "temporal_gap_hours": round(gap, 3) if gap is not None else None,
            "quality_a": quality_a, "quality_b": quality_b, "reasons": reasons,
            "abstained": True, "repair_verification": "not_inferred",
        }
    class_a = getattr(a, "damage_class", "unknown")
    class_b = getattr(b, "damage_class", "unknown")
    min_quality = min(quality_a["score"], quality_b["score"])
    min_confidence = min(quality_a["confidence_score"], quality_b["confidence_score"])

    gps_accuracy_values = [getattr(item, "gps_accuracy_m", None) for item in (a, b)]
    invalid_accuracy = any(
        value is not None and (
            not _finite_nonnegative(value)
        )
        for value in gps_accuracy_values
    )
    accuracy_exceeds_threshold = any(
        value is not None and _finite_nonnegative(value) and float(value) > threshold
        for value in gps_accuracy_values
    )

    decision = "uncertain"
    score = 0.0
    if invalid_accuracy:
        reasons.append("GPS accuracy metadata is invalid; the comparison abstains.")
    elif accuracy_exceeds_threshold:
        reasons.append("GPS accuracy exceeds the spatial threshold; the comparison abstains.")
    elif class_a != class_b:
        reasons.append("The predicted damage classes differ; visual class agreement is not strong enough for a same-damage match.")
        if distance > threshold * 1.5:
            decision = "different_damage"
            score = min(0.95, 0.55 + min(0.40, distance / max(threshold * 8.0, 1.0)))
    elif distance > threshold * 1.5:
        decision = "different_damage"
        score = min(0.95, 0.55 + min(0.40, distance / max(threshold * 8.0, 1.0)))
        reasons.append("The observations are separated by more than 1.5 times the spatial threshold.")
    elif distance > threshold:
        reasons.append("GPS separation is near the configured threshold; the comparison abstains instead of forcing a match.")
    elif gap is not None and gap < MIN_TEMPORAL_GAP_HOURS:
        reasons.append("The observations are less than 10 minutes apart and may belong to the same pass.")
    elif gap is None:
        reasons.append("Observation timestamps are unavailable; temporal comparison is insufficient.")
    elif min_quality < MIN_QUALITY_SCORE or min_confidence < 0.35:
        reasons.append("At least one observation has low confidence or quality; manual review is required.")
    else:
        spatial_score = max(0.0, 1.0 - distance / threshold)
        temporal_score = min(1.0, (gap or 0.0) / 24.0)
        score = 0.35 * spatial_score + 0.30 * ((quality_a["score"] + quality_b["score"]) / 2.0) + 0.20 * min_confidence + 0.15 * temporal_score
        score = round(max(0.0, min(1.0, score)), 4)
        if score >= 0.60:
            decision = "same_damage"
            reasons.append("Class, proximity, temporal separation and observation quality support a possible repeat sighting.")
        else:
            decision = "uncertain"
            reasons.append("Combined evidence score is below the conservative match threshold.")

    if quality_a["flags"]:
        reasons.extend(f"Observation A: {flag}." for flag in quality_a["flags"])
    if quality_b["flags"]:
        reasons.extend(f"Observation B: {flag}." for flag in quality_b["flags"])
    if gap is None:
        reasons.append("Temporal separation is unavailable.")

    return {
        "decision": decision,
        "score": round(score, 4) if score is not None else None,
        "distance_m": round(distance, 2),
        "temporal_gap_hours": round(gap, 3) if gap is not None else None,
        "quality_a": quality_a,
        "quality_b": quality_b,
        "reasons": list(dict.fromkeys(reasons)),
        "abstained": decision == "uncertain",
        "repair_verification": "not_inferred",
    }


def _finite_nonnegative(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return number >= 0 and number != float("inf") and number == number
