"""Authenticated legacy citizen-report endpoint.

This endpoint receives client-claimed counts and confidence, not an image.
Those records are explicitly marked unverified; only the server-side image
inference endpoint may create model-backed DamageObservation records.
"""
from __future__ import annotations

import logging
import math

from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from potholes.models import Pothole
from services.fastapi_client import postprocess_detection, validate_inference

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def report_pothole(request):
    """Store an authenticated, explicitly unverified citizen/client report."""
    try:
        data = request.data
    except Exception:
        return JsonResponse({"error": "Invalid request body"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "A JSON object is required"}, status=400)

    try:
        latitude = float(data["latitude"])
        longitude = float(data["longitude"])
        num_potholes = int(data["num_potholes"])
        confidence_score = float(data["confidence_score"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return JsonResponse(
            {"error": f"Missing or invalid required field: {exc}"},
            status=400,
        )

    if not (math.isfinite(latitude) and math.isfinite(longitude) and
            -90 <= latitude <= 90 and -180 <= longitude <= 180):
        return JsonResponse({"error": "Coordinates out of range"}, status=400)
    if not math.isfinite(confidence_score) or not 0.0 <= confidence_score <= 1.0:
        return JsonResponse(
            {"error": "confidence_score must be a finite number between 0.0 and 1.0"},
            status=400,
        )
    if num_potholes < 1 or num_potholes > 100:
        return JsonResponse(
            {"error": "num_potholes must be between 1 and 100"},
            status=400,
        )

    frame_number = data.get("frame_number")
    if frame_number is not None:
        try:
            frame_number = int(frame_number)
            if frame_number < 0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            return JsonResponse({"error": "frame_number must be a non-negative integer"}, status=400)

    device_id = data.get("device_id")
    if device_id is not None and (not isinstance(device_id, str) or len(device_id) > 120):
        return JsonResponse({"error": "device_id must be a string of at most 120 characters"}, status=400)

    # This legacy endpoint receives client-claimed numeric results, not the image.
    # Do not store anything when the validation service is unavailable.
    validation_result = validate_inference(
        latitude=latitude,
        longitude=longitude,
        num_potholes=num_potholes,
        confidence_score=confidence_score,
        frame_number=frame_number,
        device_id=device_id,
    )
    if validation_result is None:
        return JsonResponse(
            {"error": "Validation service is unavailable; report was not saved."},
            status=503,
        )
    if not validation_result.get("is_valid"):
        return JsonResponse(
            {
                "error": "Client-reported counts were rejected by validation.",
                "reason": validation_result.get("reason"),
            },
            status=422,
        )

    severity = validation_result.get("adjusted_severity")
    if severity not in {"low", "medium", "high", "critical"}:
        logger.error("Validation service returned an unsupported severity.")
        return JsonResponse({"error": "Validation service returned an invalid response."}, status=502)

    postprocess_result = postprocess_detection(
        latitude=latitude,
        longitude=longitude,
        num_potholes=num_potholes,
        confidence_score=confidence_score,
        adjusted_severity=severity,
        frame_number=frame_number,
    )
    if postprocess_result is None:
        return JsonResponse(
            {"error": "Post-processing service is unavailable; report was not saved."},
            status=503,
        )
    if not postprocess_result.get("should_store"):
        return JsonResponse(
            {"message": "Report received but not stored by deduplication."},
            status=200,
        )

    final_lat = postprocess_result.get("latitude")
    final_lon = postprocess_result.get("longitude")
    final_severity = postprocess_result.get("severity")
    if (
        final_lat is None or final_lon is None or
        final_severity not in {"low", "medium", "high", "critical"}
    ):
        return JsonResponse({"error": "Post-processing service returned an invalid response."}, status=502)

    # This route cannot certify a model prediction because it never receives an image.
    # Keep it available as an authenticated report, but always expose its provenance.
    client_description = str(data.get("description", "") or "").strip()[:1000]
    marker = "Client-reported observation — not verified by server-side image inference."
    final_description = f"{marker} {client_description}".strip()

    try:
        pothole = Pothole.objects.create(
            latitude=final_lat,
            longitude=final_lon,
            num_potholes=num_potholes,
            severity=final_severity,
            description=final_description,
            frame_number=frame_number,
            status="reported",
        )
    except Exception:
        logger.exception("Failed to store unverified citizen pothole report.")
        return JsonResponse({"error": "Failed to store pothole report"}, status=500)

    return JsonResponse(
        {
            "id": pothole.pk,
            "latitude": float(pothole.latitude),
            "longitude": float(pothole.longitude),
            "num_potholes": pothole.num_potholes,
            "severity": pothole.severity,
            "description": pothole.description,
            "status": pothole.status,
            "source": pothole.source,
            "timestamp": pothole.timestamp.isoformat(),
            # Kept for older clients, but cannot mean image/model verification.
            "fastapi_validated": False,
            "metadata_validation_service_used": True,
        },
        status=201,
    )
