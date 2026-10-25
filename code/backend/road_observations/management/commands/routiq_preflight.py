"""Read-only RoutIQ configuration and dependency preflight."""
from __future__ import annotations

import os
import importlib.util
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.loader import MigrationLoader


def _allowlist_check(hosts, cors_origins, csrf_origins, allow_all, credentials):
    if not hosts or "*" in hosts:
        return "BLOCKED", "Configure explicit allowed hosts."
    if allow_all or credentials:
        return "BLOCKED", "Arbitrary or credentialed cross-origin access is not permitted."
    if not cors_origins or "*" in cors_origins or not csrf_origins or "*" in csrf_origins:
        return "BLOCKED", "Configure explicit CORS and CSRF origin allowlists."
    return "PASS", "Host, CORS, and CSRF allowlists are present and do not permit wildcard origins."


def _evidence_root_check(root, media_root, static_root):
    try:
        evidence = Path(root).resolve()
        public_roots = (Path(media_root).resolve(), Path(static_root).resolve())
        if any(evidence == public or public in evidence.parents for public in public_roots):
            return "BLOCKED", "Private evidence storage is inside a public media or static directory."
        probe = evidence if evidence.exists() else evidence.parent
        if not probe.exists() or not probe.is_dir():
            return "WARNING", "The private evidence directory is outside public roots but its parent is unavailable."
        if not os.access(probe, os.W_OK):
            return "BLOCKED", "The private evidence directory is outside public roots but is not writable."
        return "PASS", "Private evidence storage is outside public roots and its directory or parent is writable."
    except (OSError, TypeError, ValueError):
        return "BLOCKED", "Private evidence storage could not be validated."


def _service_url_check(url, expected_port):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return "BLOCKED", "The service URL must be a valid HTTP(S) URL without embedded credentials."
        if parsed.port is None:
            return "WARNING", "The service URL is valid but does not specify an explicit port."
        if parsed.port != expected_port:
            return "WARNING", f"The configured service uses a non-default development port; expected {expected_port}."
        return "PASS", f"The service URL uses the expected development port {expected_port}."
    except ValueError:
        return "BLOCKED", "The service URL is malformed."


def _production_security_check(debug, ssl_redirect, session_cookie_secure, csrf_cookie_secure):
    if debug or not ssl_redirect or not session_cookie_secure or not csrf_cookie_secure:
        return "BLOCKED", "Production must disable debug and enable HTTPS redirection and secure session/CSRF cookies."
    return "PASS", "HTTPS redirection and secure session/CSRF cookies are enabled."


class Command(BaseCommand):
    help = "Report local RoutIQ readiness checks without changing project data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-service-checks", action="store_true",
            help="Skip the network request to the internal FastAPI vision service.",
        )

    def handle(self, *args, **options):
        checks = []
        secret_key = str(getattr(settings, "SECRET_KEY", ""))
        local_fallback = "routiq-local-development-key-not-for-production"
        if secret_key and secret_key != local_fallback:
            checks.append(("PASS", "Django secret configuration", "A non-default secret is configured; its value is not displayed."))
        elif getattr(settings, "DEBUG", False):
            checks.append(("WARNING", "Django secret configuration", "The local development fallback is active; configure a private secret before deployment."))
        else:
            checks.append(("BLOCKED", "Django secret configuration", "A deployment secret is not configured."))

        allow_status, allow_detail = _allowlist_check(
            getattr(settings, "ALLOWED_HOSTS", []),
            getattr(settings, "CORS_ALLOWED_ORIGINS", []),
            getattr(settings, "CSRF_TRUSTED_ORIGINS", []),
            getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False),
            getattr(settings, "CORS_ALLOW_CREDENTIALS", False),
        )
        checks.append((allow_status, "Host and origin policy", allow_detail))
        if getattr(settings, "DEPLOYMENT_ENVIRONMENT", "development") == "production":
            secure_status, secure_detail = _production_security_check(
                getattr(settings, "DEBUG", True),
                getattr(settings, "SECURE_SSL_REDIRECT", False),
                getattr(settings, "SESSION_COOKIE_SECURE", False),
                getattr(settings, "CSRF_COOKIE_SECURE", False),
            )
            checks.append((secure_status, "Production HTTPS and cookie policy", secure_detail))

        evidence_status, evidence_detail = _evidence_root_check(
            getattr(settings, "ROUTIQ_PRIVATE_EVIDENCE_ROOT", ""),
            settings.MEDIA_ROOT,
            settings.STATIC_ROOT,
        )
        checks.append((evidence_status, "Private evidence storage", evidence_detail))

        try:
            loader = MigrationLoader(connection, ignore_no_migrations=True)
            leaves = loader.graph.leaf_nodes("road_observations")
            unapplied = [node for node in leaves if node not in loader.applied_migrations]
            if unapplied:
                checks.append(("WARNING", "Road-observation migrations", "Migration state was read successfully; one or more leaf migrations remain unapplied."))
            else:
                checks.append(("PASS", "Road-observation migrations", "Migration state was read successfully and all leaf migrations are applied."))
        except Exception:
            checks.append(("NOT VERIFIED", "Road-observation migrations", "Migration state could not be read. No migration was applied."))

        django_target = os.getenv("ROUTIQ_DJANGO_URL", "http://127.0.0.1:8000")
        vision_target = os.getenv("ROUTIQ_VISION_URL", "http://127.0.0.1:8100")
        state, detail = _service_url_check(django_target, 8000)
        checks.append((state, "Django development URL", detail))
        state, detail = _service_url_check(vision_target, 8100)
        checks.append((state, "Vision-service URL", detail))

        dashcam_missing = [
            package for package in ("cvzone", "geopy", "easyocr")
            if importlib.util.find_spec(package) is None
        ]
        if dashcam_missing:
            checks.append((
                "WARNING", "Legacy dashcam dependencies",
                "Install the approved project dependencies before enabling dashcam processing; missing: "
                + ", ".join(dashcam_missing) + ".",
            ))
        else:
            checks.append(("PASS", "Legacy dashcam dependencies", "Required optional dashcam packages are available."))

        if options["skip_service_checks"]:
            checks.append(("NOT VERIFIED", "FastAPI service health", "Network readiness was skipped by request."))
            checks.append(("NOT VERIFIED", "FastAPI detector readiness", "Network readiness was skipped by request."))
        else:
            from road_observations.vision_client import (
                FastAPIVisionClient,
                VisionReadinessError,
                VisionServiceTimeout,
                VisionServiceUnavailable,
            )

            client = FastAPIVisionClient(base_url=vision_target)
            try:
                client.health()
                checks.append(("PASS", "FastAPI service health", "The liveness endpoint responded; this does not establish detector readiness."))
            except VisionServiceTimeout:
                checks.append(("BLOCKED", "FastAPI service health", "The liveness request timed out. Check service load and the configured URL."))
            except VisionServiceUnavailable:
                checks.append(("BLOCKED", "FastAPI service health", "The vision service is unreachable. Start it at the configured URL."))
            except VisionReadinessError:
                checks.append(("BLOCKED", "FastAPI service health", "The service responded with an invalid health response."))
            except Exception:
                checks.append(("NOT VERIFIED", "FastAPI service health", "The liveness check could not be completed."))

            try:
                report = client.detector_status()
                detector_status = report["status"]
                if report["inference_tested"]:
                    checks.append(("PASS", "FastAPI detector readiness", "The service reports that a real inference check was successfully executed."))
                elif detector_status == "ready_to_test":
                    checks.append(("WARNING", "FastAPI detector readiness", "Compatible labels were loaded; real inference has not been verified."))
                elif detector_status in {"disabled", "test_backend_only", "unsupported_backend", "missing_weights_path", "weights_not_found", "incompatible_labels", "dependency_missing", "model_load_failed", "invalid_configuration"}:
                    checks.append(("BLOCKED", "FastAPI detector readiness", f"Detector readiness is {detector_status.replace('_', ' ')}. Configure authorized weights and compatible labels."))
                else:
                    checks.append(("WARNING", "FastAPI detector readiness", f"Detector readiness is {detector_status.replace('_', ' ')}; inference is not verified."))
            except VisionServiceTimeout:
                checks.append(("BLOCKED", "FastAPI detector readiness", "The readiness request timed out. Check the service load and configured URL."))
            except VisionServiceUnavailable:
                checks.append(("BLOCKED", "FastAPI detector readiness", "The service is unreachable, so detector readiness cannot be checked."))
            except VisionReadinessError:
                checks.append(("BLOCKED", "FastAPI detector readiness", "The service returned invalid readiness JSON or a malformed readiness report."))
            except Exception:
                checks.append(("NOT VERIFIED", "FastAPI detector readiness", "The readiness check could not be completed."))

        for state, name, detail in checks:
            self.stdout.write(f"[{state}] {name}: {detail}")
        counts = {state: sum(result[0] == state for result in checks) for state in ("PASS", "WARNING", "BLOCKED", "NOT VERIFIED")}
        self.stdout.write(
            "Summary: " + ", ".join(f"{state}={count}" for state, count in counts.items())
        )
