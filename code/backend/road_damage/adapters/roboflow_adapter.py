"""Remote Roboflow Serverless adapter for RoutIQ road-damage inference.

The model executes in Roboflow's hosted service; this backend does not download
or load PyTorch/Ultralytics weights.
"""
from __future__ import annotations

from io import BytesIO
import math
import os
import re
from urllib.parse import quote, urlparse

import requests
from PIL import Image

from ..class_mapping import UnknownDamageClassError, normalize_label
from ..detector import DetectorNotConfiguredError
from ..schemas import Detection


MAX_REQUEST_BYTES = 4_500_000
ALLOWED_API_HOSTS = {"detect.roboflow.com", "serverless.roboflow.com"}
MODEL_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*/[0-9]+")
CLASS_IDS = {
    "longitudinal_crack": 0,
    "transverse_crack": 1,
    "alligator_crack": 2,
    "pothole": 3,
}


class RoboflowAdapter:
    """Send an in-memory image to an allowlisted Roboflow hosted model API."""

    def __init__(self, config):
        self.config = config
        self.api_key = (config.api_key or "").strip()
        self.model_id = (config.model_id or "").strip()
        self.api_url = (config.api_url or "").rstrip("/")

        if not self.api_key:
            raise DetectorNotConfiguredError(
                "ROBOFLOW_API_KEY must be configured for hosted image inference."
            )
        if not MODEL_ID_PATTERN.fullmatch(self.model_id):
            raise ValueError("ROBOFLOW_MODEL_ID must use the project/version format.")
        parsed = urlparse(self.api_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in ALLOWED_API_HOSTS
            or parsed.path not in {"", "/"}
            or parsed.username
            or parsed.password
        ):
            raise ValueError("ROBOFLOW_API_URL must use the official HTTPS hosted API.")

        self.registry = dict(CLASS_IDS)

    def _encode_image(self, image: Image.Image) -> tuple[bytes, float, float]:
        if image is None:
            raise ValueError("Image cannot be None.")

        original_width, original_height = image.size
        if original_width <= 0 or original_height <= 0:
            raise ValueError("Image dimensions must be positive.")

        candidate = image.convert("RGB")
        candidate.thumbnail((1280, 1280), Image.Resampling.LANCZOS)

        payload = b""
        for _ in range(8):
            buffer = BytesIO()
            candidate.save(buffer, format="JPEG", quality=85, optimize=True)
            payload = buffer.getvalue()
            if 0 < len(payload) <= MAX_REQUEST_BYTES:
                return (
                    payload,
                    original_width / candidate.width,
                    original_height / candidate.height,
                )
            next_width = max(1, int(candidate.width * 0.8))
            next_height = max(1, int(candidate.height * 0.8))
            if (next_width, next_height) == candidate.size:
                break
            candidate = candidate.resize(
                (next_width, next_height), Image.Resampling.LANCZOS
            )

        raise ValueError("Image could not be reduced below the hosted inference size limit.")

    def detect(self, image: Image.Image) -> list[Detection]:
        payload, scale_x, scale_y = self._encode_image(image)
        try:
            overlap = int(round(float(os.getenv("ROUTIQ_NMS_IOU_THRESHOLD", "0.45")) * 100))
        except (TypeError, ValueError):
            overlap = 45
        if not 0 <= overlap <= 100:
            overlap = 45

        endpoint = f"{self.api_url}/{quote(self.model_id, safe='/')}"
        try:
            response = requests.post(
                endpoint,
                params={
                    "api_key": self.api_key,
                    "confidence": int(round(self.config.confidence_threshold * 100)),
                    "overlap": overlap,
                },
                files={"file": ("road-image.jpg", payload, "image/jpeg")},
                timeout=(5.0, 45.0),
            )
        except requests.Timeout:
            raise RuntimeError("Roboflow hosted inference timed out.") from None
        except requests.RequestException:
            # Do not surface a transport exception: it may include the query URL.
            raise RuntimeError("Could not reach Roboflow hosted inference.") from None

        if response.status_code in (401, 403):
            raise RuntimeError("Roboflow rejected the API key or model access.") from None
        if response.status_code == 429:
            raise RuntimeError("Roboflow rate or free-credit limit was reached.") from None
        if response.status_code >= 400:
            raise RuntimeError(
                f"Roboflow hosted inference returned HTTP {response.status_code}."
            ) from None

        try:
            result = response.json()
        except ValueError:
            raise RuntimeError("Roboflow returned an invalid inference response.") from None

        predictions = result.get("predictions") if isinstance(result, dict) else None
        if not isinstance(predictions, list):
            raise RuntimeError("Roboflow response did not contain a predictions list.")

        detections: list[Detection] = []
        for prediction in predictions:
            if not isinstance(prediction, dict):
                continue
            raw_label = str(prediction.get("class", "")).strip()
            try:
                class_name = normalize_label(raw_label)
            except (UnknownDamageClassError, TypeError):
                # Ignore labels outside RoutIQ's four canonical road-damage classes.
                continue

            try:
                confidence = float(prediction.get("confidence"))
                center_x = float(prediction.get("x"))
                center_y = float(prediction.get("y"))
                width = float(prediction.get("width"))
                height = float(prediction.get("height"))
            except (TypeError, ValueError):
                continue

            if (
                not all(math.isfinite(value) for value in (confidence, center_x, center_y, width, height))
                or confidence < self.config.confidence_threshold
                or confidence > 1
                or width <= 0
                or height <= 0
            ):
                continue

            class_id_value = prediction.get("class_id")
            try:
                class_id = int(class_id_value)
            except (TypeError, ValueError):
                class_id = CLASS_IDS[class_name]

            x1 = max(0.0, (center_x - width / 2.0) * scale_x)
            y1 = max(0.0, (center_y - height / 2.0) * scale_y)
            x2 = min(float(image.width), (center_x + width / 2.0) * scale_x)
            y2 = min(float(image.height), (center_y + height / 2.0) * scale_y)
            if x2 <= x1 or y2 <= y1:
                continue

            detections.append(
                Detection(
                    class_id=max(0, class_id),
                    class_name=class_name,
                    confidence=confidence,
                    bbox=(x1, y1, x2, y2),
                    model_name=self.config.model_name or "roboflow-road-damage",
                    model_version=(
                        self.config.model_version
                        if self.config.model_version != "unversioned"
                        else self.model_id
                    ),
                )
            )

        return detections
