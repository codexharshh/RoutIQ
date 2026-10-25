"""Django client for the stateless internal RoutIQ FastAPI vision service."""
from __future__ import annotations

import math
import os
from io import BytesIO

from PIL import Image

import requests

from road_damage.detector import DetectorNotConfiguredError
from road_damage.schemas import Detection


class VisionServiceUnavailable(RuntimeError):
    """The configured vision service could not be reached."""


class VisionServiceTimeout(RuntimeError):
    """The configured vision service did not respond within its timeout."""


class VisionReadinessError(RuntimeError):
    """The service responded but did not provide a valid readiness report."""


MAX_VISION_REQUEST_BYTES = 19 * 1024 * 1024


def _encode_image_for_vision(image: Image.Image) -> tuple[bytes, float, float]:
    """Encode an image below FastAPI's 20 MiB cap and return bbox scale factors."""
    if image is None:
        raise ValueError("Image cannot be None")

    original_width, original_height = image.size
    if original_width <= 0 or original_height <= 0:
        raise ValueError("Image dimensions must be positive")

    candidate = image.convert("RGB")
    for _attempt in range(10):
        buffer = BytesIO()
        candidate.save(buffer, format="JPEG", quality=88, optimize=True)
        payload = buffer.getvalue()
        if 0 < len(payload) <= MAX_VISION_REQUEST_BYTES:
            return (
                payload,
                original_width / candidate.width,
                original_height / candidate.height,
            )

        factor = min(0.90, math.sqrt(MAX_VISION_REQUEST_BYTES * 0.85 / max(1, len(payload))))
        next_width = max(1, int(candidate.width * factor))
        next_height = max(1, int(candidate.height * factor))
        if (next_width, next_height) == candidate.size:
            next_width = max(1, int(candidate.width * 0.85))
            next_height = max(1, int(candidate.height * 0.85))
        if (next_width, next_height) == candidate.size:
            break
        candidate = candidate.resize((next_width, next_height), Image.Resampling.LANCZOS)

    raise ValueError("Image cannot be encoded below the vision service upload limit.")


class FastAPIVisionClient:
    """Send an in-memory image to FastAPI; Django remains the system of record."""

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or os.getenv("ROUTIQ_VISION_URL", "http://127.0.0.1:8100")).rstrip("/")
        self.timeout = timeout or float(os.getenv("ROUTIQ_VISION_TIMEOUT", "120"))

    def detect(self, image):
        if image is None:
            raise ValueError("Image cannot be None")

        payload_bytes, scale_x, scale_y = _encode_image_for_vision(image)
        try:
            response = requests.post(
                f"{self.base_url}/detect",
                data=payload_bytes,
                headers={"Content-Type": "application/octet-stream"},
                timeout=(3.0, self.timeout),
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"RoutIQ Vision Service is unreachable at {self.base_url}. Start the FastAPI vision service. ({type(exc).__name__})"
            ) from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.status_code == 503:
            detail = str(payload.get("detail", "")) if isinstance(payload, dict) else ""
            if "not configured" in detail.lower() or "disabled" in detail.lower():
                raise DetectorNotConfiguredError(detail or "RoutIQ vision model is not configured.")
            raise RuntimeError(detail or "RoutIQ Vision Service is not ready.")

        if not response.ok:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            raise RuntimeError(f"RoutIQ Vision Service returned HTTP {response.status_code}: {detail or 'Inference request failed.'}")

        if not isinstance(payload, dict) or not isinstance(payload.get("detections"), list):
            raise RuntimeError("RoutIQ Vision Service returned an invalid response.")
        count = payload.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count != len(payload["detections"]):
            raise RuntimeError("RoutIQ Vision Service returned an inconsistent detection count.")

        detections = []
        for item in payload["detections"]:
            if not isinstance(item, dict):
                raise RuntimeError("RoutIQ Vision Service returned a malformed detection.")
            class_id = item.get("class_id")
            confidence = item.get("confidence")
            bbox = item.get("bbox")
            if (
                isinstance(class_id, bool) or not isinstance(class_id, int)
                or not isinstance(item.get("class_name"), str)
                or isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not isinstance(bbox, list) or len(bbox) != 4
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in bbox)
                or not isinstance(item.get("model_name", "routiq-model"), str)
                or not isinstance(item.get("model_version", "configured"), str)
            ):
                raise RuntimeError("RoutIQ Vision Service returned a malformed detection.")
            try:
                detections.append(Detection(
                    class_id=class_id,
                    class_name=item["class_name"],
                    confidence=confidence,
                    # The vision service may resize large images to stay under
                    # its request cap; map boxes back to the original upload pixels.
                    bbox=(
                        float(bbox[0]) * scale_x,
                        float(bbox[1]) * scale_y,
                        float(bbox[2]) * scale_x,
                        float(bbox[3]) * scale_y,
                    ),
                    model_name=item.get("model_name", "routiq-model"),
                    model_version=item.get("model_version", "configured"),
                ))
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("RoutIQ Vision Service returned an invalid detection.") from exc
        return detections

    def detector_status(self):
        """Return a sanitized detector preflight report from the vision service."""
        try:
            response = requests.get(
                f"{self.base_url}/detector-status",
                timeout=(3.0, min(self.timeout, 15.0)),
            )
        except requests.Timeout as exc:
            raise VisionServiceTimeout("RoutIQ Vision Service readiness timed out.") from exc
        except requests.ConnectionError as exc:
            raise VisionServiceUnavailable("RoutIQ Vision Service is unavailable.") from exc
        except requests.RequestException as exc:
            raise VisionServiceUnavailable("RoutIQ Vision Service is unavailable.") from exc
        if not response.ok:
            raise VisionReadinessError("RoutIQ Vision Service could not report detector readiness.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise VisionReadinessError("RoutIQ Vision Service returned an invalid readiness response.") from exc
        statuses = {
            "disabled", "test_backend_only", "unsupported_backend", "missing_weights_path",
            "weights_not_found", "invalid_weights_path", "invalid_configuration",
            "weights_present_unverified", "ready_to_test", "model_loaded_labels_unavailable",
            "incompatible_labels", "dependency_missing", "model_load_failed",
        }
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str) or payload["status"] not in statuses:
            raise VisionReadinessError("RoutIQ Vision Service returned an invalid readiness response.")
        labels = payload.get("labels", "not_checked")
        if not isinstance(labels, str) or labels not in {"not_checked", "compatible", "incompatible"}:
            raise VisionReadinessError("RoutIQ Vision Service returned an invalid readiness response.")
        tested = payload.get("inference_tested", False)
        if not isinstance(tested, bool):
            raise VisionReadinessError("RoutIQ Vision Service returned an invalid readiness response.")
        return {
            "status": payload["status"],
            "labels": labels,
            "inference_tested": tested,
        }

    def health(self):
        """Check FastAPI liveness without inferring detector readiness."""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=(3.0, 5.0))
        except requests.Timeout as exc:
            raise VisionServiceTimeout("RoutIQ Vision Service health check timed out.") from exc
        except requests.ConnectionError as exc:
            raise VisionServiceUnavailable("RoutIQ Vision Service is unavailable.") from exc
        except requests.RequestException as exc:
            raise VisionServiceUnavailable("RoutIQ Vision Service is unavailable.") from exc
        if not response.ok:
            raise VisionReadinessError("RoutIQ Vision Service health endpoint returned an error.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise VisionReadinessError("RoutIQ Vision Service returned an invalid health response.") from exc
        if payload != {"status": "ok", "service": "routiq-vision"}:
            raise VisionReadinessError("RoutIQ Vision Service returned an invalid health response.")
        return {"status": "ok", "service": "routiq-vision"}
