import os
from . import __doc__ as _package_doc
from ..class_mapping import build_class_registry, UnknownDamageClassError
from ..schemas import Detection


class IncompatibleModelLabelsError(RuntimeError):
    """Raised when loaded model classes cannot map to RoutIQ's supported labels."""

class UltralyticsAdapter:
    def __init__(self, config):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Ultralytics is not installed in this environment") from exc

        self.config = config
        weights = config.checked_weights_path()
        self.model = YOLO(str(weights))
        try:
            self.registry = build_class_registry(self.model.names)
        except (UnknownDamageClassError, ValueError) as exc:
            raise IncompatibleModelLabelsError(
                "The model labels do not map to RoutIQ's supported damage classes."
            ) from exc

    def detect(self, image):
        if image is None:
            raise ValueError("Image cannot be None")
        results = self.model.predict(
            source=image,
            conf=self.config.confidence_threshold,
            iou=float(os.environ.get("ROUTIQ_NMS_IOU_THRESHOLD", "0.45")),
            device=self.config.device,
            verbose=False,
        )
        found = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                class_id = int(box.cls.item())
                if class_id not in self.registry:
                    raise ValueError(f"Unmapped model class ID: {class_id}")
                found.append(Detection(
                    class_id=class_id,
                    class_name=self.registry[class_id],
                    confidence=float(box.conf.item()),
                    bbox=tuple(float(v) for v in box.xyxy[0].tolist()),
                    model_name=self.config.model_name,
                    model_version=self.config.model_version,
                ))
        return found
