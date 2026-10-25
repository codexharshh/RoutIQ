# Legacy Dashcam Integration

The authenticated legacy video endpoint can optionally persist trustworthy per-detection output through the modern `DamageObservation` model. Django remains the system of record. Without an authenticated owner or a complete per-detection record, processing remains confined to the legacy workflow; aggregate frame counts are never expanded into invented observations.

## Per-detection contract

The processor writes a separate `routiq_per_detection.csv` containing a stable source ID, generated upload/video identifier, frame number, timestamp, matched GPS coordinates and source file, class ID and mapped class name, confidence, and bounding box. The adapter validates every row before creating modern observations. It accepts only the supported legacy `pothole` class and finite, bounded coordinates, confidence, and box values. Rows without an actual GPS match are not exported as geographically located observations.

The authenticated upload endpoint supplies the Django user ID and generated video identifier. Persistence uses the existing owner-scoped inspection session and observation idempotency key, so reprocessing the same source for the same owner does not create duplicate observations. The same source processed by another owner is isolated into that owner's session. This uses the existing schema and requires no migration.

The legacy aggregate `Pothole` synchronization remains for compatibility. It is not a source for modern per-detection observations. Modern dashcam observations currently retain detection metadata and GPS provenance, but this adapter does not retain a private frame image for each detection; private evidence review therefore depends on separate uploaded image evidence.

## Runtime limitations

The processor requires the existing OpenCV, GPS parser, YOLO adapter, `cvzone`, `geopy`, and OCR runtime dependencies, as well as a configured compatible model. The current environment does not have `cvzone`, `geopy`, or `easyocr` installed, and no compatible local weights were found, so actual video inference and end-to-end processing have not been verified. The ingestion tests exercise the documented CSV contract with deterministic test rows; they do not simulate real inference or establish detector accuracy.

The legacy GPS parser supplies its source timestamp and matched coordinates. The adapter preserves those values and records the GPS source file. It does not infer camera capture location when GPS is missing and does not claim that browser/device location represents the video location.
