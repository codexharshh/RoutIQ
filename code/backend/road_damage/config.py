import os
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class DetectorConfig:
    backend: str = "disabled"
    weights_path: str = ""
    confidence_threshold: float = 0.25
    device: str = "cpu"
    model_name: str = "routiq-road-damage"
    model_version: str = "unversioned"

    @classmethod
    def from_env(cls):
        threshold = float(os.getenv("ROUTIQ_CONFIDENCE_THRESHOLD", "0.25"))
        if not 0 <= threshold <= 1:
            raise ValueError("ROUTIQ_CONFIDENCE_THRESHOLD must be between 0 and 1")
        return cls(
            backend=os.getenv("ROUTIQ_DETECTOR_BACKEND", "disabled").strip().lower(),
            weights_path=os.getenv("ROUTIQ_MODEL_WEIGHTS", "").strip(),
            confidence_threshold=threshold,
            device=os.getenv("ROUTIQ_DETECTOR_DEVICE", "cpu").strip(),
            model_name=os.getenv("ROUTIQ_MODEL_NAME", "routiq-road-damage").strip(),
            model_version=os.getenv("ROUTIQ_MODEL_VERSION", "unversioned").strip(),
        )

    def checked_weights_path(self):
        if not self.weights_path:
            raise ValueError("Configure an authorized local model file first")
        path = Path(self.weights_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Model weights not found: {path}")
        return path

    def preflight(self):
        """Report configuration readiness without importing or loading a model."""
        if self.backend in ("", "disabled"):
            return {"status": "disabled", "labels": "not_checked"}
        if self.backend == "mock":
            return {"status": "test_backend_only", "labels": "not_checked"}
        if self.backend != "ultralytics":
            return {"status": "unsupported_backend", "labels": "not_checked"}
        if not self.weights_path:
            return {"status": "missing_weights_path", "labels": "not_checked"}
        try:
            self.checked_weights_path()
        except FileNotFoundError:
            return {"status": "weights_not_found", "labels": "not_checked"}
        except (OSError, RuntimeError, ValueError):
            return {"status": "invalid_weights_path", "labels": "not_checked"}
        return {"status": "weights_present_unverified", "labels": "not_checked"}
