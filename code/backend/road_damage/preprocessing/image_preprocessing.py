from pathlib import Path

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024

def validate_image_upload(filename, size_bytes):
    if Path(filename).suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Unsupported image extension")
    if size_bytes <= 0 or size_bytes > MAX_IMAGE_BYTES:
        raise ValueError("Image size must be between 1 byte and 20 MB")
    return True
