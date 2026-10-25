"""Authenticated endpoints for legacy dashcam video and GPS processing."""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

logger = logging.getLogger(__name__)
MAX_VIDEO_BYTES = 500 * 1024 * 1024
MAX_GPS_BYTES = 50 * 1024 * 1024
MAX_FILES_PER_UPLOAD = 10
MAX_DISTANCE_THRESHOLD_M = 100.0
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov"}


def _valid_video_header(suffix: str, header: bytes) -> bool:
    if suffix in {".mp4", ".mov"}:
        return len(header) >= 8 and header[4:8] == b"ftyp"
    if suffix == ".avi":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI "
    return False


def _upload_root(user) -> Path:
    storage_root = (Path(settings.MEDIA_ROOT) / "uploads").resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    root = _safe_child(storage_root, str(user.pk))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_child(parent: Path, name: str) -> Path:
    child = (parent / name).resolve()
    if child.parent != parent.resolve():
        raise ValueError("Invalid upload identifier.")
    return child


def _save_uploads(request, *, category: str, suffixes: set[str], max_bytes: int):
    files = request.FILES.getlist("files")
    if not files or len(files) > MAX_FILES_PER_UPLOAD:
        return None, Response(
            {"detail": f"Upload between 1 and {MAX_FILES_PER_UPLOAD} files."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if sum(uploaded.size for uploaded in files) > max_bytes:
        return None, Response(
            {"detail": f"The total upload must not exceed {max_bytes // (1024 * 1024)} MB."},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    root = _upload_root(request.user)
    batch_id = uuid.uuid4().hex
    directory = _safe_child(root, f"{category}-{batch_id}")
    directory.mkdir()
    identifiers = []
    try:
        for uploaded in files:
            suffix = Path(uploaded.name).suffix.lower()
            if suffix not in suffixes:
                raise ValueError(f"Unsupported {category} file type.")
            if uploaded.size <= 0 or uploaded.size > max_bytes:
                raise ValueError(f"Each file must be between 1 byte and {max_bytes // (1024 * 1024)} MB.")
            file_id = uuid.uuid4().hex
            destination = _safe_child(directory, f"{file_id}{suffix}")
            first_bytes = bytearray()
            gps_tokens = set()
            rolling = b""
            with destination.open("xb") as target:
                for chunk in uploaded.chunks():
                    target.write(chunk)
                    if len(first_bytes) < 32:
                        first_bytes.extend(chunk[:32 - len(first_bytes)])
                    if category == "gps":
                        scan = rolling + chunk
                        for token in (b"$GPRMC", b"$GPGGA"):
                            if token in scan:
                                gps_tokens.add(token)
                        rolling = scan[-8:]
            if category == "videos" and not _valid_video_header(suffix, bytes(first_bytes)):
                raise ValueError("The uploaded file does not match its declared video format.")
            if category == "gps" and gps_tokens != {b"$GPRMC", b"$GPGGA"}:
                raise ValueError("The GPS trace must contain both GPRMC and GPGGA records.")
            identifiers.append(file_id)
    except (OSError, ValueError) as exc:
        shutil.rmtree(directory, ignore_errors=True)
        return None, Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return (batch_id, identifiers), None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_videos(request):
    """Save bounded video uploads under generated, user-scoped names."""
    result, error = _save_uploads(
        request, category="videos", suffixes=VIDEO_SUFFIXES, max_bytes=MAX_VIDEO_BYTES
    )
    if error:
        return error
    batch_id, identifiers = result
    return Response({"success": True, "batch_id": batch_id, "uploaded_files": identifiers})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_gps(request):
    """Save bounded GPS trace uploads under generated, user-scoped names."""
    result, error = _save_uploads(
        request, category="gps", suffixes={".git", ".txt", ".nmea", ".log"}, max_bytes=MAX_GPS_BYTES
    )
    if error:
        return error
    batch_id, identifiers = result
    return Response({"success": True, "upload_directory": batch_id, "uploaded_files": identifiers})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def process_video(request):
    """Process only files previously uploaded by this authenticated user."""
    try:
        data = request.data
        video_id = str(data.get("video_id", ""))
        gps_batch_id = str(data.get("gps_batch_id", ""))
        distance_threshold = float(data.get("distance_threshold", 2.5))
        if not video_id.isalnum() or len(video_id) != 32 or not gps_batch_id.isalnum() or len(gps_batch_id) != 32:
            raise ValueError("Select a video and GPS batch uploaded in this session.")
        if not 0.5 <= distance_threshold <= MAX_DISTANCE_THRESHOLD_M:
            raise ValueError("Distance threshold must be between 0.5 and 100 meters.")
        root = _upload_root(request.user)
        gps_directory = _safe_child(root, f"gps-{gps_batch_id}")
        matches = [
            _safe_child(_safe_child(root, f"videos-{_batch}"), f"{video_id}{suffix}")
            for _batch in _owned_batch_ids(root, "videos")
            for suffix in VIDEO_SUFFIXES
        ]
        video_path = next((path for path in matches if path.is_file()), None)
        if video_path is None or not gps_directory.is_dir():
            raise ValueError("The selected video or GPS batch is unavailable. Upload both files again.")
    except (ValueError, TypeError) as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    try:
        call_command(
            "process_dashcam_video", video_path=str(video_path),
            gps_directory=str(gps_directory), distance_threshold=distance_threshold,
            owner_id=request.user.pk, source_identifier=video_id,
        )
    except Exception:
        logger.exception("Dashcam processing failed for user %s", request.user.pk)
        return Response({"detail": "Video processing failed. Check the server logs."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response({"success": True, "message": "Video processing completed successfully."})


def _owned_batch_ids(root: Path, category: str) -> list[str]:
    prefix = f"{category}-"
    return [path.name[len(prefix):] for path in root.glob(f"{prefix}*") if path.is_dir()]


@api_view(["POST"])
@permission_classes([IsAdminUser])
def cleanup_uploads(request):
    """Remove only temporary upload directories belonging to the administrator."""
    root = _upload_root(request.user)
    for category in ("videos", "gps"):
        for path in root.glob(f"{category}-*"):
            resolved = path.resolve()
            if resolved.parent == root and resolved.is_dir():
                shutil.rmtree(resolved)
    return Response({"success": True, "message": "Your temporary uploads were removed."})
