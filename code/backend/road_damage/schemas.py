from dataclasses import dataclass

import math

CANONICAL_CLASSES = {
    "pothole",
    "longitudinal_crack",
    "transverse_crack",
    "alligator_crack",
}

@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple
    model_name: str = "unknown"
    model_version: str = "unknown"

    def __post_init__(self):
        if self.class_id < 0:
            raise ValueError("class_id must be non-negative")
        if self.class_name not in CANONICAL_CLASSES:
            raise ValueError("Unsupported damage class")
        confidence = float(self.confidence)
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Confidence must be from 0 to 1")
        if len(self.bbox) != 4:
            raise ValueError("bbox requires x1, y1, x2, y2")
        x1, y1, x2, y2 = map(float, self.bbox)
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
            raise ValueError("Bounding-box coordinates must be finite numbers")
        if min(x1, y1, x2, y2) < 0 or x2 <= x1 or y2 <= y1:
            raise ValueError("Invalid bounding box")
        if not self.model_name.strip():
            raise ValueError("model_name is required")

    def to_dict(self):
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "confidence": float(self.confidence),
            "bbox": list(map(float, self.bbox)),
            "model_name": self.model_name,
            "model_version": self.model_version,
        }
