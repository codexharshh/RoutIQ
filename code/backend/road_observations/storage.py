"""Private filesystem storage for retained observation evidence."""
from pathlib import Path
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible
from django.utils import timezone


def evidence_expiry(session):
    """Return the explicit expiry or a retention-based expiry for legacy files."""
    if session.evidence_expires_at is not None:
        return session.evidence_expires_at
    retention_days = max(1, int(getattr(settings, "ROUTIQ_EVIDENCE_RETENTION_DAYS", 30)))
    return session.created_at + timedelta(days=retention_days)


@deconstructible
class PrivateEvidenceStorage(FileSystemStorage):
    """Store evidence outside MEDIA_ROOT with restrictive local permissions."""

    def __init__(self):
        location = getattr(
            settings,
            "ROUTIQ_PRIVATE_EVIDENCE_ROOT",
            settings.BASE_DIR / "private_evidence",
        )
        resolved_location = Path(location).resolve()
        media_root = Path(settings.MEDIA_ROOT).resolve()
        static_root = Path(settings.STATIC_ROOT).resolve()
        roots = (media_root, static_root)
        if any(resolved_location == root or root in resolved_location.parents for root in roots):
            raise ImproperlyConfigured("Private evidence storage must be outside public media and static roots.")
        super().__init__(
            location=str(resolved_location),
            base_url=None,
            file_permissions_mode=0o600,
            directory_permissions_mode=0o700,
        )

    def url(self, name):
        """Private evidence has no static URL; use the authenticated API view."""
        raise ValueError("Private evidence is available only through its authenticated API endpoint.")
