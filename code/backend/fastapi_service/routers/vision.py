"""Stateless RoutIQ image-inference endpoint for the internal vision service."""
from __future__ import annotations

import logging
from io import BytesIO

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError
from road_damage.config import DetectorConfig
from fastapi_service.schemas import DetectorReadinessResponse

router = APIRouter()
logger = logging.getLogger("fastapi_service.vision")
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
_detector = None


def get_detector():
    """Initialize the ML model lazily so health checks do not load weights."""
    global _detector
    if _detector is None:
        from road_damage.detector import create_detector
        _detector = create_detector()
    return _detector


@router.post("/detect")
async def detect_image(request: Request):
    """Accept raw image bytes and return model detections; never writes to a DB."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BYTES:
                raise HTTPException(status_code=413, detail="Image must not exceed 20 MB.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid content length.")

    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="Image must not exceed 20 MB.")
        raw.extend(chunk)
    if not raw:
        raise HTTPException(status_code=400, detail="No image bytes were provided.")

    try:
        raw_bytes = bytes(raw)
        with Image.open(BytesIO(raw_bytes)) as check:
            check.verify()
        with Image.open(BytesIO(raw_bytes)) as source:
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                raise HTTPException(status_code=413, detail="Image dimensions are too large.")
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=400, detail="The supplied bytes are not a supported image.")

    try:
        # Model initialization and synchronous inference must not block the event loop.
        detections = await run_in_threadpool(lambda: get_detector().detect(image))
    except Exception as exc:
        from road_damage.detector import DetectorNotConfiguredError
        if isinstance(exc, DetectorNotConfiguredError):
            raise HTTPException(status_code=503, detail="RoutIQ vision model is not configured.")
        logger.exception("RoutIQ inference failed")
        if isinstance(exc, (FileNotFoundError, RuntimeError, ValueError)):
            raise HTTPException(status_code=503, detail="RoutIQ vision model is not ready. Check model configuration and service logs.")
        raise HTTPException(status_code=500, detail="RoutIQ inference failed.")

    return {"count": len(detections), "detections": [item.to_dict() for item in detections]}


@router.get("/detector-status", response_model=DetectorReadinessResponse)
async def detector_status():
    """Explicitly preflight configured weights and labels; this may load the model."""
    try:
        config = DetectorConfig.from_env()
    except (TypeError, ValueError):
        return {
            "status": "invalid_configuration",
            "labels": "not_checked",
            "service": "routiq-vision",
            "inference_tested": False,
        }
    report = config.preflight()
    report.update({"service": "routiq-vision", "inference_tested": False})
    if report["status"] != "weights_present_unverified":
        return report

    try:
        detector = get_detector()
        registry = getattr(detector, "registry", None)
        if not registry:
            report.update({"status": "model_loaded_labels_unavailable", "labels": "not_checked"})
            return report
        report.update({
            "status": "ready_to_test",
            "labels": "compatible",
            "class_ids": sorted(registry),
        })
    except ImportError:
        report.update({"status": "dependency_missing", "labels": "not_checked"})
    except Exception as exc:
        from road_damage.adapters.ultralytics_adapter import IncompatibleModelLabelsError
        if isinstance(exc, IncompatibleModelLabelsError):
            report.update({"status": "incompatible_labels", "labels": "incompatible"})
        elif isinstance(exc, FileNotFoundError):
            report.update({"status": "weights_not_found", "labels": "not_checked"})
        else:
            logger.warning("Detector preflight could not load the configured model (%s)", type(exc).__name__)
            report.update({"status": "model_load_failed", "labels": "not_checked"})
    return report
