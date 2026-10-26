import os
from dataclasses import dataclass, field
from pathlib import Path
import re
from urllib.parse import urlparse

@dataclass(frozen=True)
class DetectorConfig:
    backend: str = "disabled"
    weights_path: str = ""
    confidence_threshold: float = 0.25
    device: str = "cpu"
    model_name: str = "routiq-road-damage"
    model_version: str = "unversioned"
    api_key: str = field(default="", repr=False)
    model_id: str = "road-damages-detection/1"
    api_url: str = "https://detect.roboflow.com"

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
            api_key=os.getenv("ROBOFLOW_API_KEY", "").strip(),
            model_id=os.getenv("ROBOFLOW_MODEL_ID", "road-damages-detection/1").strip(),
            api_url=os.getenv("ROBOFLOW_API_URL", "https://detect.roboflow.com").strip().rstrip("/"),
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
        if self.backend == "roboflow":
            if not self.api_key:
                return {"status": "missing_api_key", "labels": "not_checked"}
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*/[0-9]+", self.model_id):
                return {"status": "invalid_model_id", "labels": "not_checked"}
            parsed = urlparse(self.api_url)
            if parsed.scheme != "https" or parsed.hostname not in {"detect.roboflow.com", "serverless.roboflow.com"} or parsed.path not in {"", "/"} or parsed.username or parsed.password:
                return {"status": "invalid_api_url", "labels": "not_checked"}
            return {"status": "remote_configured", "labels": "not_checked"}
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
