from .config import DetectorConfig
from .schemas import Detection

class DetectorNotConfiguredError(RuntimeError):
    pass

class MockDetector:
    """Test detector. Returns only explicitly supplied detections."""
    def __init__(self, detections=()):
        self.detections = list(detections)

    def detect(self, image):
        if image is None:
            raise ValueError("Image cannot be None")
        return list(self.detections)

class DisabledDetector:
    def detect(self, image):
        raise DetectorNotConfiguredError(
            "Detection is disabled until a permitted model is configured."
        )

def create_detector(config=None):
    config = config or DetectorConfig.from_env()
    if config.backend == "mock":
        raise DetectorNotConfiguredError(
            "The mock detector is available only in isolated tests and cannot serve application requests."
        )
    if config.backend in ("", "disabled"):
        return DisabledDetector()
    if config.backend == "ultralytics":
        from .adapters.ultralytics_adapter import UltralyticsAdapter
        return UltralyticsAdapter(config)
    raise ValueError(f"Unsupported detector backend: {config.backend}")
