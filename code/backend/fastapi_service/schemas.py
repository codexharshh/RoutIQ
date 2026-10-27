"""
Input/Output Pydantic schemas for the RoutIQ FastAPI internal service.

All schemas define exactly what Django sends and what FastAPI returns.
FastAPI NEVER communicates with PostgreSQL directly — Django owns the DB.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


# ── /validate ────────────────────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    """
    ML inference result forwarded by Django after receiving it from Flutter.
    confidence_score is the model's output confidence (0.0–1.0).
    """
    latitude: float = Field(..., ge=-90, le=90, description="WGS-84 latitude")
    longitude: float = Field(..., ge=-180, le=180, description="WGS-84 longitude")
    num_potholes: int = Field(..., ge=0, description="Pothole count from on-device ML")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Model confidence")
    frame_number: Optional[int] = Field(None, description="Frame index from dashcam feed")
    device_id: Optional[str] = Field(None, description="Unique Flutter device identifier")


class ValidateResponse(BaseModel):
    """
    Validation result returned to Django.
    If is_valid=False, Django should reject the report with the given reason.
    """
    is_valid: bool
    reason: Optional[str] = None       # populated only when is_valid=False
    adjusted_severity: SeverityLevel   # computed from confidence + count
    confidence_score: float


# ── /postprocess ─────────────────────────────────────────────────────────────

class PostprocessRequest(BaseModel):
    """Validated detection data to be cleaned and enriched before DB storage."""
    latitude: float
    longitude: float
    num_potholes: int
    confidence_score: float
    adjusted_severity: SeverityLevel
    frame_number: Optional[int] = None


class PostprocessResponse(BaseModel):
    """
    Enriched data ready for Django to write to PostgreSQL.
    should_store=False means Django should silently discard this report.
    """
    latitude: float
    longitude: float
    num_potholes: int
    severity: SeverityLevel
    description: str            # human-readable summary auto-generated here
    should_store: bool          # False = duplicate / noise; Django must skip


# ── /analytics ───────────────────────────────────────────────────────────────

class AnalyticsRequest(BaseModel):
    """Aggregation request — pothole records from a Django queryset."""
    pothole_records: list[dict]


class HotspotPoint(BaseModel):
    latitude: float
    longitude: float
    count: int
    severity: SeverityLevel


class AnalyticsResponse(BaseModel):
    total_count: int
    severity_distribution: dict[str, int]
    hotspots: list[HotspotPoint]
    avg_confidence: float


class ServiceHealthResponse(BaseModel):
    """Liveness contract; it does not indicate detector readiness."""

    status: Literal["ok"]
    service: Literal["routiq-vision"]


class DetectorReadinessResponse(BaseModel):
    """Sanitized detector configuration and verification state."""

    status: Literal[
        "disabled", "test_backend_only", "unsupported_backend", "missing_weights_path",
        "weights_not_found", "invalid_weights_path", "invalid_configuration",
        "weights_present_unverified", "ready_to_test", "model_loaded_labels_unavailable",
        "incompatible_labels", "dependency_missing", "model_load_failed", "remote_configured",
    ]
    labels: Literal["not_checked", "compatible", "incompatible"]
    service: Literal["routiq-vision"] = "routiq-vision"
    inference_tested: bool = False
    class_ids: list[int] | None = None
