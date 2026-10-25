"""HTTP client for RoutIQ's private FastAPI validation and analytics service.

The service URL is configured with ROUTIQ_VISION_URL and defaults to loopback
for local development. The public function names are retained for compatibility
with the legacy report endpoint until that endpoint is migrated and tested.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)
ROUTIQ_VISION_URL = os.getenv("ROUTIQ_VISION_URL", "http://127.0.0.1:8100").rstrip("/")
ROUTIQ_VISION_TIMEOUT = float(os.getenv("ROUTIQ_VISION_TIMEOUT", "5"))
_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    """Create a standard HTTP client using RoutIQ's configured internal URL."""
    return httpx.Client(base_url=ROUTIQ_VISION_URL, timeout=ROUTIQ_VISION_TIMEOUT)


def _get_or_create_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = _get_client()
    return _client


def _post(endpoint: str, payload: dict) -> dict | None:
    """POST JSON; return None on service failure so caller fallback can run."""
    client = _get_or_create_client()
    try:
        response = client.post(endpoint, json=payload)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            logger.error("RoutIQ Vision Service returned a non-object response on %s", endpoint)
            return None
        return result
    except httpx.TimeoutException:
        logger.warning("RoutIQ Vision Service timed out on %s after %.1fs", endpoint, ROUTIQ_VISION_TIMEOUT)
    except httpx.ConnectError:
        logger.error("Cannot connect to RoutIQ Vision Service at %s; is the service running?", ROUTIQ_VISION_URL)
    except httpx.HTTPStatusError as exc:
        logger.error("RoutIQ Vision Service returned HTTP %s on %s: %s", exc.response.status_code, endpoint, exc.response.text[:200])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected RoutIQ Vision Service error on %s: %s", endpoint, exc)
    return None


def validate_inference(
    latitude: float,
    longitude: float,
    num_potholes: int,
    confidence_score: float,
    frame_number: int | None = None,
    device_id: str | None = None,
) -> dict | None:
    return _post("/validate", {
        "latitude": latitude,
        "longitude": longitude,
        "num_potholes": num_potholes,
        "confidence_score": confidence_score,
        "frame_number": frame_number,
        "device_id": device_id,
    })


def postprocess_detection(
    latitude: float,
    longitude: float,
    num_potholes: int,
    confidence_score: float,
    adjusted_severity: str,
    frame_number: int | None = None,
) -> dict | None:
    return _post("/postprocess", {
        "latitude": latitude,
        "longitude": longitude,
        "num_potholes": num_potholes,
        "confidence_score": confidence_score,
        "adjusted_severity": adjusted_severity,
        "frame_number": frame_number,
    })


def compute_analytics(pothole_records: list[dict]) -> dict | None:
    return _post("/analytics", {"pothole_records": pothole_records})


def check_fastapi_health() -> bool:
    """Check liveness of the configured RoutIQ internal service."""
    client = _get_or_create_client()
    try:
        response = client.get("/health")
        return response.status_code == 200
    except Exception:
        logger.debug("RoutIQ Vision Service health check failed", exc_info=True)
        return False