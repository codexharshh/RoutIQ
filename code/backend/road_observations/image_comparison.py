"""Conservative visual comparison of owner-authorized road inspection images.

This module produces review cues. It does not infer or prove a road repair.
"""
from __future__ import annotations

from io import BytesIO

from django.utils import timezone

from .storage import evidence_expiry

MAX_EVIDENCE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_SIDE = 1280
METHOD = "orb_homography_ssim_v1"


def _unavailable(reason: str) -> dict:
    return {
        "available": False,
        "status": "insufficient_evidence",
        "explanation": reason,
        "metrics": {},
        "method": METHOD,
    }


def _read_rgb(session):
    if not session.image_evidence:
        return None, "No retained image evidence is available for this inspection session."
    try:
        expiry = evidence_expiry(session)
    except Exception:
        return None, "The evidence retention status could not be verified."
    if expiry <= timezone.now():
        return None, "The retained image evidence has expired. Upload a new inspection image to compare it."
    try:
        with session.image_evidence.open("rb") as handle:
            raw = handle.read(MAX_EVIDENCE_BYTES + 1)
    except (OSError, ValueError):
        return None, "The retained image file could not be opened."
    if len(raw) > MAX_EVIDENCE_BYTES:
        return None, "The retained image exceeds the visual-comparison size limit."
    try:
        import numpy as np
        from PIL import Image, ImageOps
        with Image.open(BytesIO(raw)) as opened:
            width, height = opened.size
            if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                return None, "The retained image dimensions are outside the supported range."
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            rgb = np.asarray(image)
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            return None, "The retained file is not a supported RGB image."
        return rgb, None
    except Exception:
        return None, "The retained file could not be decoded as a supported image."


def compare_session_images(session_a, session_b) -> dict:
    """Align two images, report measurable differences, and abstain when evidence is weak."""
    if session_a.pk == session_b.pk:
        return _unavailable("Choose two different inspection sessions.")

    rgb_a, error_a = _read_rgb(session_a)
    if rgb_a is None:
        return _unavailable(f"Reference image unavailable: {error_a}")
    rgb_b, error_b = _read_rgb(session_b)
    if rgb_b is None:
        return _unavailable(f"Comparison image unavailable: {error_b}")

    try:
        import cv2
        import numpy as np
        from skimage.metrics import structural_similarity
    except Exception:
        return _unavailable("The local image-comparison dependencies are not available. No visual score was produced.")

    gray_a = cv2.cvtColor(rgb_a, cv2.COLOR_RGB2GRAY)
    gray_b = cv2.cvtColor(rgb_b, cv2.COLOR_RGB2GRAY)
    blur_a = float(cv2.Laplacian(gray_a, cv2.CV_64F).var())
    blur_b = float(cv2.Laplacian(gray_b, cv2.CV_64F).var())
    brightness_a = float(gray_a.mean())
    brightness_b = float(gray_b.mean())
    flags = []
    if blur_a < 18:
        flags.append("Reference image may be blurred or lack texture.")
    if blur_b < 18:
        flags.append("Comparison image may be blurred or lack texture.")
    if brightness_a < 25 or brightness_a > 232:
        flags.append("Reference image exposure may be unsuitable.")
    if brightness_b < 25 or brightness_b > 232:
        flags.append("Comparison image exposure may be unsuitable.")

    metrics = {
        "blur_score_a": round(blur_a, 2),
        "blur_score_b": round(blur_b, 2),
        "brightness_a": round(brightness_a, 2),
        "brightness_b": round(brightness_b, 2),
        "image_width_a": int(rgb_a.shape[1]),
        "image_height_a": int(rgb_a.shape[0]),
        "image_width_b": int(rgb_b.shape[1]),
        "image_height_b": int(rgb_b.shape[0]),
    }

    def finish(status, explanation, available=True, **extra):
        final_metrics = dict(metrics)
        final_metrics.update(extra)
        return {
            "available": available,
            "status": status,
            "explanation": explanation,
            "metrics": final_metrics,
            "quality_flags": list(flags),
            "method": METHOD,
        }

    try:
        orb = cv2.ORB_create(nfeatures=2500, scaleFactor=1.2, nlevels=8)
        key_a, desc_a = orb.detectAndCompute(gray_a, None)
        key_b, desc_b = orb.detectAndCompute(gray_b, None)
        if desc_a is None or desc_b is None or len(key_a) < 12 or len(key_b) < 12:
            return finish("insufficient_evidence", "Too few stable visual features were found to align these images reliably.", feature_matches=0, homography_inliers=0, alignment_ratio=0.0, overlap_percent=0.0)

        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        pairs = matcher.knnMatch(desc_b, desc_a, k=2)
        good = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance]
        if len(good) < 12:
            return finish("insufficient_evidence", "The images do not share enough reliable features for a trustworthy visual alignment.", feature_matches=len(good), homography_inliers=0, alignment_ratio=0.0, overlap_percent=0.0)

        pts_b = np.float32([key_b[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        pts_a = np.float32([key_a[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        homography, inlier_mask = cv2.findHomography(pts_b, pts_a, cv2.RANSAC, 4.0)
        if homography is None or inlier_mask is None:
            return finish("insufficient_evidence", "A stable geometric alignment could not be estimated for these images.", feature_matches=len(good), homography_inliers=0, alignment_ratio=0.0, overlap_percent=0.0)

        inliers = int(inlier_mask.ravel().sum())
        alignment_ratio = float(inliers / max(1, len(good)))
        height_a, width_a = gray_a.shape[:2]
        height_b, width_b = gray_b.shape[:2]
        aligned_b = cv2.warpPerspective(gray_b, homography, (width_a, height_a), flags=cv2.INTER_LINEAR)
        source_mask = np.full((height_b, width_b), 255, dtype=np.uint8)
        valid_mask = cv2.warpPerspective(source_mask, homography, (width_a, height_a), flags=cv2.INTER_NEAREST) > 0
        overlap_percent = float(valid_mask.mean() * 100)
        metrics.update({
            "feature_matches": int(len(good)),
            "homography_inliers": inliers,
            "alignment_ratio": round(alignment_ratio, 3),
            "overlap_percent": round(overlap_percent, 2),
        })

        if inliers < 10 or alignment_ratio < 0.30 or overlap_percent < 25:
            return finish("insufficient_evidence", "Image alignment or shared road-surface overlap is too weak. Capture both images from a similar position and angle.")

        _, ssim_map = structural_similarity(gray_a, aligned_b, full=True, data_range=255)
        valid_count = int(valid_mask.sum())
        if valid_count < 1000:
            return finish("insufficient_evidence", "Too little overlapping image area remains for meaningful visual comparison.")
        diff = cv2.absdiff(gray_a, aligned_b)
        changed_percent = float((np.logical_and(diff > 28, valid_mask).sum() / valid_count) * 100)
        masked_ssim = float(np.asarray(ssim_map)[valid_mask].mean())
        metrics.update({
            "structural_similarity": round(masked_ssim, 4),
            "changed_pixel_percent": round(changed_percent, 2),
        })

        if flags:
            return finish("insufficient_evidence", "Visual alignment was possible, but image quality warnings make the comparison inconclusive: " + " ".join(flags))
        if masked_ssim >= 0.82 and changed_percent <= 16:
            return finish("candidate_visual_similarity", "The aligned image regions look broadly similar. This is a review cue, not proof that damage persists or that a repair has or has not occurred.")
        if masked_ssim <= 0.62 or changed_percent >= 32:
            return finish("candidate_visual_change", "The aligned images contain notable visual differences. These may reflect road changes, viewpoint, lighting, shadows, water or traffic; manual review is required.")
        return finish("mixed_visual_evidence", "The visual comparison is mixed. Use manual review and other evidence rather than drawing a repair conclusion from image similarity alone.")
    except Exception:
        return finish("insufficient_evidence", "Visual comparison could not be completed reliably. No repair conclusion was inferred.")
