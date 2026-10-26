import logging
from datetime import timedelta
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import FileResponse
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    InspectionSession,
    DamageInstance,
    DamageObservation,
    DamageStatusAssessment,
    DAMAGE_CLASSES,
    DAMAGE_STATUSES,
)
from .serializers import (
    InspectionSessionSerializer,
    DamageObservationSerializer,
    AssessmentInputSerializer,
)
from .services.observation_service import create_observation
from road_damage.detector import DetectorNotConfiguredError
from .vision_client import (
    FastAPIVisionClient,
    VisionReadinessError,
    VisionServiceTimeout,
    VisionServiceUnavailable,
)
from .coordinates import extract_photo_gps, parse_coordinate_pair
from .storage import evidence_expiry

logger = logging.getLogger(__name__)
_detector = None

def get_detector():
    """Return the stateless FastAPI vision client (model runs in FastAPI, not Django)."""
    global _detector
    if _detector is None:
        _detector = FastAPIVisionClient()
    return _detector


class SessionListCreateView(generics.ListCreateAPIView):
    serializer_class = InspectionSessionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return InspectionSession.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ObservationListCreateView(generics.ListCreateAPIView):
    serializer_class = DamageObservationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return DamageObservation.objects.filter(
            session__owner=self.request.user
        ).select_related("session", "instance")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            observation, created = create_observation(
                owner=request.user,
                validated_data=dict(serializer.validated_data),
            )
        except PermissionDenied:
            return Response(
                {"detail": "You cannot write to that inspection session."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(
            self.get_serializer(observation).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class DetectImageView(APIView):
    permission_classes = [IsAuthenticated]
    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    max_bytes = 20 * 1024 * 1024
    max_pixels = 40_000_000

    def post(self, request):
        image_file = request.FILES.get("image")
        if image_file is None:
            return Response(
                {"detail": "Upload an image using the 'image' field."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if Path(image_file.name).suffix.lower() not in self.allowed_extensions:
            return Response({"detail": "Unsupported image extension."},
                            status=status.HTTP_400_BAD_REQUEST)

        if image_file.size <= 0 or image_file.size > self.max_bytes:
            return Response({"detail": "Image must be between 1 byte and 20 MB."},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        coordinate_source = request.data.get("coordinate_source", "unspecified")
        if coordinate_source not in {"unspecified", "device_current", "manual", "photo_exif"}:
            return Response({"detail": "Coordinate source must be unspecified, device_current, manual, or photo_exif."},
                            status=status.HTTP_400_BAD_REQUEST)
        raw_lat, raw_lon = request.data.get("latitude"), request.data.get("longitude")
        latitude = longitude = None
        if coordinate_source == "photo_exif":
            if raw_lat not in (None, "") or raw_lon not in (None, ""):
                return Response({"detail": "Photo GPS coordinates are read from image metadata; do not submit coordinates with photo_exif."},
                                status=status.HTTP_400_BAD_REQUEST)
        elif raw_lat in (None, "") and raw_lon in (None, ""):
            if coordinate_source != "unspecified":
                return Response({"detail": "A coordinate source requires valid coordinates."},
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            try:
                latitude, longitude = parse_coordinate_pair(raw_lat, raw_lon)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        raw_accuracy = request.data.get("gps_accuracy_m")
        gps_accuracy_m = None
        if raw_accuracy not in (None, ""):
            try:
                gps_accuracy_m = float(raw_accuracy)
            except (TypeError, ValueError):
                return Response({"detail": "GPS accuracy must be a non-negative number."},
                                status=status.HTTP_400_BAD_REQUEST)
            if not 0 <= gps_accuracy_m < float("inf"):
                return Response({"detail": "GPS accuracy must be a finite non-negative number."},
                                status=status.HTTP_400_BAD_REQUEST)

        try:
            image_file.seek(0)
            evidence_bytes = image_file.read()
            from PIL import Image, ImageOps, UnidentifiedImageError

            with Image.open(BytesIO(evidence_bytes)) as check:
                check.verify()

            with Image.open(BytesIO(evidence_bytes)) as source:
                source.load()
                # Extract GPS from the original EXIF block before orientation is applied.
                photo_gps = extract_photo_gps(source) if coordinate_source == "photo_exif" else None
                oriented = ImageOps.exif_transpose(source)
                width, height = oriented.size
                if width <= 0 or height <= 0 or width * height > self.max_pixels:
                    return Response({"detail": "Image dimensions are too large."},
                                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
                image = oriented.convert("RGB")

        except ImportError:
            return Response({"detail": "Pillow is required for image decoding."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception:
            return Response({"detail": "Uploaded file is not a valid supported image."},
                            status=status.HTTP_400_BAD_REQUEST)

        if coordinate_source == "photo_exif":
            if photo_gps is None:
                return Response({"detail": "The image does not contain valid GPS metadata."},
                                status=status.HTTP_400_BAD_REQUEST)
            latitude, longitude, exif_accuracy = photo_gps
            if raw_accuracy not in (None, ""):
                return Response({"detail": "GPS accuracy for photo metadata must come from the image metadata."},
                                status=status.HTTP_400_BAD_REQUEST)
            gps_accuracy_m = exif_accuracy

        try:
            detections = get_detector().detect(image)
        except DetectorNotConfiguredError:
            return Response(
                {"detail": "AI detector is disabled. Configure a permitted local model first."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            logger.warning("RoutIQ detector is unavailable: %s", type(exc).__name__)
            return Response(
                {"detail": "AI detector is not ready. Check model configuration and server logs."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            logger.exception("Unexpected RoutIQ inference failure")
            return Response({"detail": "Image inference failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        now = timezone.now()
        clean_name = Path(image_file.name.replace("\\", "/")).name[:255]

        try:
            with transaction.atomic():
                session = InspectionSession.objects.create(
                    owner=request.user,
                    title=f"Image inspection: {clean_name}",
                    source_kind="image",
                    status="completed",
                    started_at=now,
                    ended_at=now,
                    metadata={"width": width, "height": height,
                              "coordinate_source": coordinate_source},
                )

                suffix = Path(image_file.name).suffix.lower()
                session.image_evidence.save(
                    f"{session.session_key}{suffix}",
                    ContentFile(evidence_bytes),
                    save=False,
                )
                retention_days = max(1, int(getattr(settings, "ROUTIQ_EVIDENCE_RETENTION_DAYS", 30)))
                session.evidence_expires_at = now + timedelta(days=retention_days)
                session.save(update_fields=["image_evidence", "evidence_expires_at"])

                observations = []
                for det in detections:
                    damage_class = det.class_name
                    instance = DamageInstance.objects.create(
                        created_by=request.user,
                        damage_class=damage_class,
                        current_status="unknown",
                        latitude=latitude,
                        longitude=longitude,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    observations.append(DamageObservation.objects.create(
                        session=session,
                        instance=instance,
                        damage_class=damage_class,
                        class_id=det.class_id,
                        confidence=det.confidence,
                        bbox=list(det.bbox),
                        latitude=latitude,
                        longitude=longitude,
                        gps_accuracy_m=gps_accuracy_m,
                        observed_at=now,
                        source_name=clean_name,
                        model_name=det.model_name,
                        model_version=det.model_version,
                        metadata={"image_width": width, "image_height": height,
                                  "coordinate_source": coordinate_source,
                                  "observation_source": "model_inference"},
                    ))

        except Exception:
            if "session" in locals() and session.image_evidence:
                session.image_evidence.delete(save=False)
            logger.exception("Failed to persist RoutIQ inference results")
            return Response({"detail": "Detections could not be saved."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "count": len(observations),
            "session_id": session.pk,
            "results": DamageObservationSerializer(observations, many=True).data,
            "detail": "Inference completed and results saved.",
        }, status=status.HTTP_201_CREATED)


class DetectorReadinessView(APIView):
    """Expose sanitized internal detector readiness to authenticated users."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            report = get_detector().detector_status()
        except VisionServiceTimeout:
            return Response({"status": "vision_timeout", "labels": "not_checked", "inference_tested": False},
                            status=status.HTTP_200_OK)
        except VisionServiceUnavailable:
            return Response({"status": "vision_unavailable", "labels": "not_checked", "inference_tested": False},
                            status=status.HTTP_200_OK)
        except VisionReadinessError:
            return Response({"status": "invalid_readiness_response", "labels": "not_checked", "inference_tested": False},
                            status=status.HTTP_200_OK)
        except Exception as exc:
            logger.warning("Detector readiness could not be validated: %s", type(exc).__name__)
            return Response({"status": "invalid_readiness_response", "labels": "not_checked", "inference_tested": False},
                            status=status.HTTP_200_OK)
        return Response(report)


class SessionEvidenceView(APIView):
    """Serve or delete retained images through owner-scoped API access only."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        session = get_object_or_404(InspectionSession, pk=pk, owner=request.user)
        if not session.image_evidence:
            return Response({"detail": "No retained image evidence is available."}, status=404)
        if evidence_expiry(session) <= timezone.now():
            return Response({"detail": "The retained image evidence has expired."}, status=410)
        try:
            evidence_file = session.image_evidence.open("rb")
        except FileNotFoundError:
            logger.warning("Retained evidence file is missing for session %s", session.pk)
            return Response(
                {"detail": "The retained image file is no longer available in storage. Re-upload this image to retain it."},
                status=status.HTTP_410_GONE,
            )
        except OSError:
            logger.exception("Private evidence storage read failed for session %s", session.pk)
            return Response(
                {"detail": "Private evidence storage is temporarily unavailable. Please retry later."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        response = FileResponse(
            evidence_file,
            content_type="application/octet-stream",
            as_attachment=True,
            filename="observation-evidence",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def delete(self, request, pk):
        session = get_object_or_404(InspectionSession, pk=pk, owner=request.user)
        if session.image_evidence:
            session.image_evidence.delete(save=False)
        session.evidence_expires_at = None
        session.save(update_fields=["image_evidence", "evidence_expires_at"])
        return Response(status=204)


class ObservationAssessmentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        observation = get_object_or_404(
            DamageObservation.objects.select_related("instance"),
            pk=pk,
            session__owner=request.user,
        )
        if not observation.instance_id:
            return Response({"detail": "Observation has no damage instance."},
                            status=status.HTTP_409_CONFLICT)

        serializer = AssessmentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data

        with transaction.atomic():
            assessment = DamageStatusAssessment.objects.create(
                damage_instance=observation.instance,
                status=values["status"],
                confidence=values["confidence"],
                rationale=values.get("rationale", ""),
                evidence=values.get("evidence", {}),
                independently_verified=False,
                assessed_by=request.user,
            )
            observation.instance.current_status = values["status"]
            observation.instance.save(update_fields=["current_status", "updated_at"])

        return Response({
            "id": assessment.pk,
            "status": assessment.status,
            "confidence": assessment.confidence,
            "independently_verified": False,
        }, status=status.HTTP_201_CREATED)

class RoadDamageMapView(APIView):
    """Return only the signed-in user's observations that have usable GPS."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = (
            DamageObservation.objects.filter(
                session__owner=request.user,
                latitude__isnull=False,
                longitude__isnull=False,
                latitude__gte=-90,
                latitude__lte=90,
                longitude__gte=-180,
                longitude__lte=180,
            )
            .select_related("instance")
            .order_by("-observed_at")[:5000]
        )
        return Response([
            {
                "id": observation.id,
                "damage_class": observation.damage_class,
                "confidence": observation.confidence,
                "latitude": float(observation.latitude),
                "longitude": float(observation.longitude),
                "coordinate_source": (observation.metadata or {}).get("coordinate_source", "unspecified"),
                "observation_source": (observation.metadata or {}).get("observation_source", "unknown"),
                "gps_accuracy_m": observation.gps_accuracy_m,
                "status": observation.instance.current_status if observation.instance_id else "unknown",
                "observed_at": observation.observed_at.isoformat(),
            }
            for observation in queryset
        ])



class RoadDamageStatsView(APIView):
    """Aggregated AI-observation metrics for the authenticated RoutIQ user."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        observations = DamageObservation.objects.filter(
            session__owner=request.user
        ).select_related("instance")
        mapped = observations.filter(
            latitude__isnull=False, longitude__isnull=False
        )
        most_recent = observations.order_by("-observed_at").values_list("observed_at", flat=True).first()
        return Response({
            "total_observations": observations.count(),
            "mapped_observations": mapped.count(),
            "sessions": InspectionSession.objects.filter(owner=request.user).count(),
            "by_class": {
                key: observations.filter(damage_class=key).count()
                for key, _label in DAMAGE_CLASSES
            },
            "by_status": {
                key: observations.filter(instance__current_status=key).count()
                for key, _label in DAMAGE_STATUSES
            },
            "last_observed_at": most_recent.isoformat() if most_recent else None,
        })
