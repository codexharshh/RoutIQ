"""Transparent observation-quality scoring for RoutIQ temporal review.

This is a deterministic heuristic, not a calibrated probability. Flags make missing
metadata visible instead of silently treating it as perfect evidence.
"""
from __future__ import annotations


def _number(value):
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def observation_quality(observation):
    confidence = _number(getattr(observation, "confidence", None))
    confidence = max(0.0, min(1.0, confidence if confidence is not None else 0.0))
    flags = []

    latitude = getattr(observation, "latitude", None)
    longitude = getattr(observation, "longitude", None)
    has_gps = latitude is not None and longitude is not None
    raw_gps_accuracy = getattr(observation, "gps_accuracy_m", None)
    gps_accuracy = _number(raw_gps_accuracy)
    if not has_gps:
        gps_score = 0.0
        flags.append("GPS coordinates are missing")
    elif raw_gps_accuracy is not None and (gps_accuracy is None or gps_accuracy < 0):
        gps_score = 0.0
        flags.append("GPS accuracy is invalid")
    elif gps_accuracy is None:
        gps_score = 0.55
        flags.append("GPS accuracy was not recorded")
    elif gps_accuracy <= 5:
        gps_score = 1.0
    elif gps_accuracy <= 15:
        gps_score = 0.85
    elif gps_accuracy <= 30:
        gps_score = 0.65
    else:
        gps_score = 0.30
        flags.append("GPS accuracy is coarse (>30 m)")

    metadata = getattr(observation, "metadata", None) or {}
    width = _number(metadata.get("image_width")) if isinstance(metadata, dict) else None
    height = _number(metadata.get("image_height")) if isinstance(metadata, dict) else None
    if width and height and width > 0 and height > 0:
        short_side = min(width, height)
        if short_side >= 720:
            image_score = 1.0
        elif short_side >= 360:
            image_score = 0.82
        elif short_side >= 180:
            image_score = 0.62
        else:
            image_score = 0.35
            flags.append("Image dimensions are low for spatial comparison")
    else:
        image_score = 0.60
        flags.append("Image dimensions were not recorded")

    score = 0.40 * confidence + 0.35 * gps_score + 0.25 * image_score
    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "confidence_score": round(confidence, 4),
        "gps_score": round(gps_score, 4),
        "image_score": round(image_score, 4),
        "flags": flags,
    }
