from pathlib import PureWindowsPath, PurePosixPath
import math
from django.utils import timezone
from rest_framework import serializers
from .models import InspectionSession, DamageObservation, DAMAGE_CLASSES, DAMAGE_STATUSES
from .storage import evidence_expiry

class InspectionSessionSerializer(serializers.ModelSerializer):
    owner = serializers.PrimaryKeyRelatedField(read_only=True)
    evidence_available = serializers.SerializerMethodField()
    class Meta:
        model = InspectionSession
        fields = [
            "id", "session_key", "owner", "title", "source_kind", "status",
            "started_at", "ended_at", "metadata", "evidence_expires_at",
            "created_at", "evidence_available",
        ]
        read_only_fields = ["id", "owner", "session_key", "created_at", "evidence_expires_at"]

    def get_evidence_available(self, obj):
        return bool(obj.image_evidence and evidence_expiry(obj) > timezone.now())

    def validate_metadata(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("metadata must be an object")
        return value

class DamageObservationSerializer(serializers.ModelSerializer):
    assessment_status = serializers.SerializerMethodField()
    confidence = serializers.FloatField(read_only=True)
    class Meta:
        model = DamageObservation
        fields = "__all__"
        # Model identity and prediction evidence can only be populated by the
        # server-side inference path. The generic observation endpoint is manual.
        read_only_fields = [
            "id", "created_at", "class_id", "confidence", "bbox",
            "model_name", "model_version", "source_name", "observed_at",
        ]

    def get_assessment_status(self, obj):
        return obj.instance.current_status if obj.instance_id else "unknown"

    def validate(self, attrs):
        lat, lon = attrs.get("latitude"), attrs.get("longitude")
        if (lat is None) != (lon is None):
            raise serializers.ValidationError("Latitude and longitude must be supplied together.")
        if lat is not None and not -90 <= float(lat) <= 90:
            raise serializers.ValidationError({"latitude": "Must be from -90 to 90."})
        if lon is not None and not -180 <= float(lon) <= 180:
            raise serializers.ValidationError({"longitude": "Must be from -180 to 180."})
        accuracy = attrs.get("gps_accuracy_m")
        if accuracy is not None and not math.isfinite(float(accuracy)):
            raise serializers.ValidationError({"gps_accuracy_m": "Must be a finite number."})
        metadata = attrs.get("metadata") or {}
        coordinate_source = metadata.get("coordinate_source", "unspecified")
        if coordinate_source not in {"unspecified", "manual", "device_current"}:
            raise serializers.ValidationError({
                "metadata": "Photo EXIF provenance is assigned only by the image-upload endpoint."
            })
        if lat is None and coordinate_source != "unspecified":
            raise serializers.ValidationError({"metadata": "A coordinate source requires coordinates."})
        bbox = attrs.get("bbox")
        if bbox is not None:
            try:
                if len(bbox) != 4:
                    raise ValueError
                x1, y1, x2, y2 = map(float, bbox)
                if min(x1, y1, x2, y2) < 0 or x2 <= x1 or y2 <= y1:
                    raise ValueError
            except (TypeError, ValueError):
                raise serializers.ValidationError({"bbox": "Expected [x1, y1, x2, y2]."})
        source = attrs.get("source_name", "")
        if source and (PureWindowsPath(source).name != source or PurePosixPath(source).name != source):
            raise serializers.ValidationError({"source_name": "Use a filename only, not a path."})
        return attrs

class AssessmentInputSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[x for x in DAMAGE_STATUSES if x[0] != "unknown"])
    confidence = serializers.FloatField(min_value=0, max_value=1)
    rationale = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    evidence = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        if attrs["status"] == "appears_resolved" and (
            not attrs.get("evidence") or len(attrs.get("rationale", "").strip()) < 20
        ):
            raise serializers.ValidationError(
                "Appears resolved requires evidence and a rationale. This is not proof of repair."
            )
        return attrs
