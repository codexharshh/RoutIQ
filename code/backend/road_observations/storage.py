"""Private storage for retained inspection evidence.

Use a private Supabase Storage bucket in hosted environments so files survive
container replacement and free-service restarts. Local development retains a
restricted FileSystemStorage fallback.
"""
import logging
import mimetypes
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import File
from django.core.files.storage import FileSystemStorage
from django.core.files.utils import validate_file_name
from django.utils.deconstruct import deconstructible
from datetime import timedelta

logger = logging.getLogger(__name__)


def evidence_expiry(session):
    """Return the explicit expiry or a retention-based expiry for legacy files."""
    if session.evidence_expires_at is not None:
        return session.evidence_expires_at
    retention_days = max(1, int(getattr(settings, "ROUTIQ_EVIDENCE_RETENTION_DAYS", 30)))
    return session.created_at + timedelta(days=retention_days)


@deconstructible
class PrivateEvidenceStorage(FileSystemStorage):
    """Store private evidence in Supabase Storage when configured, else locally.

    SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY must be a backend-only
    secret. The target bucket must remain private. Files are served only by
    the authenticated, owner-scoped Django endpoint.
    """

    def __init__(self):
        self.supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
        self.supabase_key = (
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
            or os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        )
        self.supabase_bucket = os.environ.get(
            "ROUTIQ_EVIDENCE_BUCKET", "routiq-private-evidence"
        ).strip()
        self.use_supabase = bool(self.supabase_url and self.supabase_key)

        if bool(self.supabase_url) != bool(self.supabase_key):
            logger.warning(
                "Supabase evidence storage is partially configured; "
                "set both SUPABASE_URL and a backend-only storage key."
            )

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

    def _checked_name(self, name):
        normalized = str(name).replace("\\", "/")
        validate_file_name(normalized, allow_relative_path=True)
        if any(part in {"", ".", ".."} for part in normalized.split("/")):
            raise ValueError("Invalid private evidence path.")
        return normalized

    def _object_url(self, name):
        safe_name = self._checked_name(name)
        bucket = quote(self.supabase_bucket, safe="")
        path = quote(safe_name, safe="/")
        return f"{self.supabase_url}/storage/v1/object/{bucket}/{path}"

    def _auth_headers(self):
        # Supabase's newer sb_secret_ keys are API keys, not JWTs.
        # Send them only through apikey; the legacy service_role JWT may
        # also be used as a Bearer token to retain backward compatibility.
        headers = {"apikey": self.supabase_key}
        if not self.supabase_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.supabase_key}"
        return headers

    def get_available_name(self, name, max_length=None):
        if not self.use_supabase:
            return super().get_available_name(name, max_length=max_length)
        normalized = self._checked_name(name)
        if max_length is not None and len(normalized) > max_length:
            raise ValueError("Private evidence path exceeds the configured maximum length.")
        # Session evidence filenames contain UUIDs, so collisions are not expected.
        # Do not issue an extra network request just to choose a unique name.
        return normalized

    def _save(self, name, content):
        if not self.use_supabase:
            return super()._save(name, content)

        name = self._checked_name(name)
        try:
            if hasattr(content, "seek"):
                content.seek(0)
            if hasattr(content, "chunks"):
                body = b"".join(content.chunks())
            else:
                body = content.read()
            headers = self._auth_headers()
            headers.update({
                "Content-Type": getattr(content, "content_type", None)
                or mimetypes.guess_type(name)[0]
                or "application/octet-stream",
                "x-upsert": "true",
            })
            response = requests.post(
                self._object_url(name),
                data=body,
                headers=headers,
                timeout=(10, 120),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Private evidence upload failed with storage HTTP status %s",
                         getattr(getattr(exc, "response", None), "status_code", "unavailable"))
            raise OSError("Private evidence storage upload failed.") from exc
        return name

    @staticmethod
    def _response_message(response):
        """Return a short storage error summary without logging credentials."""
        try:
            payload = response.json()
        except ValueError:
            return response.text[:240]
        if isinstance(payload, dict):
            return str(
                payload.get("message")
                or payload.get("error_description")
                or payload.get("error")
                or payload.get("statusCode")
                or "Storage request rejected."
            )[:240]
        return "Storage request rejected."

    def _create_signed_url(self, name, expires_in=60):
        """Create a short-lived URL for an object in the private bucket."""
        name = self._checked_name(name)
        bucket = quote(self.supabase_bucket, safe="")
        path = quote(name, safe="/")
        endpoint = f"{self.supabase_url}/storage/v1/object/sign/{bucket}/{path}"
        response = requests.post(
            endpoint,
            json={"expiresIn": expires_in},
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            timeout=(10, 30),
        )
        if response.status_code in (400, 404):
            message = self._response_message(response)
            normalized = message.lower()
            if any(term in normalized for term in (
                "object not found", "does not exist", "no such object",
                "not found", "object does not exist",
            )):
                raise FileNotFoundError(name)
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error(
                "Private evidence signed-URL request failed with storage HTTP status %s (%s)",
                getattr(getattr(exc, "response", None), "status_code", "unavailable"),
                self._response_message(exc.response) if getattr(exc, "response", None) is not None else "no response",
            )
            raise OSError("Private evidence storage authorization failed.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise OSError("Private evidence storage returned an invalid signed-URL response.") from exc
        signed_path = payload.get("signedURL") or payload.get("signedUrl")
        if not isinstance(signed_path, str) or not signed_path:
            raise OSError("Private evidence storage did not return a signed URL.")
        if signed_path.startswith("https://") or signed_path.startswith("http://"):
            return signed_path
        if signed_path.startswith("/storage/v1/"):
            return f"{self.supabase_url}{signed_path}"
        if signed_path.startswith("/"):
            return f"{self.supabase_url}/storage/v1{signed_path}"
        return f"{self.supabase_url}/storage/v1/{signed_path}"

    def _open(self, name, mode="rb"):
        if not self.use_supabase:
            return super()._open(name, mode)
        if mode not in {"rb", "r"}:
            raise ValueError("Private evidence storage is read-only when opened; use save() to upload.")
        try:
            signed_url = self._create_signed_url(name)
            response = requests.get(signed_url, timeout=(10, 60))
            if response.status_code == 404:
                raise FileNotFoundError(name)
            response.raise_for_status()
        except FileNotFoundError:
            raise
        except requests.RequestException as exc:
            logger.error(
                "Private evidence download failed with storage HTTP status %s (%s)",
                getattr(getattr(exc, "response", None), "status_code", "unavailable"),
                self._response_message(exc.response) if getattr(exc, "response", None) is not None else "no response",
            )
            raise OSError("Private evidence storage download failed.") from exc
        except OSError:
            raise
        return File(BytesIO(response.content), name=name)

    def exists(self, name):
        if not self.use_supabase:
            return super().exists(name)
        try:
            self._create_signed_url(name)
            return True
        except FileNotFoundError:
            return False

    def delete(self, name):
        if not self.use_supabase:
            return super().delete(name)
        try:
            response = requests.delete(
                f"{self.supabase_url}/storage/v1/object/{quote(self.supabase_bucket, safe='')}",
                json={"prefixes": [self._checked_name(name)]},
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                timeout=(10, 60),
            )
            if response.status_code == 404:
                return
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Private evidence delete failed with storage HTTP status %s",
                         getattr(getattr(exc, "response", None), "status_code", "unavailable"))
            raise OSError("Private evidence storage delete failed.") from exc

    def size(self, name):
        if not self.use_supabase:
            return super().size(name)
        try:
            response = requests.head(self._create_signed_url(name), timeout=(10, 30))
            if response.status_code == 404:
                raise FileNotFoundError(name)
            response.raise_for_status()
            return int(response.headers.get("Content-Length", "0"))
        except FileNotFoundError:
            raise
        except requests.RequestException as exc:
            logger.error(
                "Private evidence size lookup failed with storage HTTP status %s",
                getattr(getattr(exc, "response", None), "status_code", "unavailable"),
            )
            raise OSError("Private evidence storage size lookup failed.") from exc

    def path(self, name):
        if self.use_supabase:
            raise ValueError("Remote private evidence does not have a local filesystem path.")
        return super().path(name)

    def url(self, name):
        """Private evidence has no public URL; use the authenticated API endpoint."""
        raise ValueError("Private evidence is available only through its authenticated API endpoint.")
