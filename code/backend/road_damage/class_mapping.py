import re

class UnknownDamageClassError(ValueError):
    pass

ALIASES = {
    "pothole": "pothole",
    "potholes": "pothole",
    "d40": "pothole",
    "longitudinal crack": "longitudinal_crack",
    "longitudinal cracks": "longitudinal_crack",
    "d00": "longitudinal_crack",
    "transverse crack": "transverse_crack",
    "transverse cracks": "transverse_crack",
    "d10": "transverse_crack",
    "alligator crack": "alligator_crack",
    "alligator cracks": "alligator_crack",
    "d20": "alligator_crack",
}

def normalize_label(label):
    if not isinstance(label, str) or not label.strip():
        raise UnknownDamageClassError("Empty model class label")
    key = label.strip().lower().replace("_", " ").replace("-", " ")
    key = re.sub(r"\s+", " ", key).replace(":", " ").strip()
    if key in ALIASES:
        return ALIASES[key]
    for prefix, value in (
        ("d00 ", "longitudinal_crack"),
        ("d10 ", "transverse_crack"),
        ("d20 ", "alligator_crack"),
        ("d40 ", "pothole"),
    ):
        if key.startswith(prefix):
            return value
    raise UnknownDamageClassError(f"Unknown damage class: {label!r}")

def build_class_registry(model_names):
    pairs = model_names.items() if isinstance(model_names, dict) else enumerate(model_names)
    registry = {}
    for class_id, label in pairs:
        class_id = int(class_id)
        if class_id < 0:
            raise ValueError("Class ID must be non-negative")
        registry[class_id] = normalize_label(str(label))
    if not registry:
        raise ValueError("The model has no class names")
    return registry
