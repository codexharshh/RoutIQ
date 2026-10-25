import uuid
import math
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from .storage import PrivateEvidenceStorage

DAMAGE_CLASSES = [
    ("pothole", "Pothole"),
    ("longitudinal_crack", "Longitudinal crack"),
    ("transverse_crack", "Transverse crack"),
    ("alligator_crack", "Alligator crack"),
]
DAMAGE_STATUSES = [
    ("unknown", "Unknown"),
    ("damage_persists", "Damage persists"),
    ("appears_resolved", "Appears resolved"),
    ("new_damage", "New damage"),
    ("uncertain", "Uncertain"),
    ("insufficient_evidence", "Insufficient evidence"),
]

class InspectionSession(models.Model):
    session_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="routiq_sessions")
    title = models.CharField(max_length=200, blank=True)
    source_kind = models.CharField(max_length=20, choices=[
        ("image", "Image"), ("video", "Video"), ("dashcam", "Dashcam"), ("manual", "Manual")
    ], default="image")
    status = models.CharField(max_length=20, choices=[
        ("open", "Open"), ("processing", "Processing"), ("completed", "Completed"), ("failed", "Failed")
    ], default="open")
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    image_evidence = models.ImageField(storage=PrivateEvidenceStorage(), upload_to="sessions/", blank=True)
    evidence_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"RoutIQ inspection {self.session_key}"

class DamageInstance(models.Model):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    damage_class = models.CharField(max_length=32, choices=DAMAGE_CLASSES)
    current_status = models.CharField(max_length=32, choices=DAMAGE_STATUSES, default="unknown")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    road_segment = models.CharField(max_length=200, blank=True)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["damage_class", "current_status"])]

class DamageObservation(models.Model):
    session = models.ForeignKey(InspectionSession, on_delete=models.CASCADE, related_name="observations")
    instance = models.ForeignKey(DamageInstance, on_delete=models.SET_NULL, null=True, blank=True, related_name="observations")
    damage_class = models.CharField(max_length=32, choices=DAMAGE_CLASSES)
    class_id = models.PositiveIntegerField(null=True, blank=True)
    confidence = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(1)])
    bbox = models.JSONField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    gps_accuracy_m = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0)])
    observed_at = models.DateTimeField(default=timezone.now)
    frame_number = models.PositiveIntegerField(null=True, blank=True)
    source_name = models.CharField(max_length=255, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    model_version = models.CharField(max_length=120, blank=True)
    idempotency_key = models.CharField(max_length=120, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observed_at"]
        indexes = [models.Index(fields=["damage_class", "observed_at"])]
        constraints = [models.UniqueConstraint(
            fields=["session", "idempotency_key"],
            condition=Q(idempotency_key__isnull=False),
            name="uniq_routiq_observation_key",
        )]

    def clean(self):
        errors = {}
        if (self.latitude is None) != (self.longitude is None):
            errors["latitude"] = "Latitude and longitude must be supplied together."
        if self.latitude is not None and not -90 <= float(self.latitude) <= 90:
            errors["latitude"] = "Latitude must be from -90 to 90."
        if self.longitude is not None and not -180 <= float(self.longitude) <= 180:
            errors["longitude"] = "Longitude must be from -180 to 180."
        if self.bbox is not None:
            try:
                if len(self.bbox) != 4:
                    raise ValueError
                x1, y1, x2, y2 = map(float, self.bbox)
                if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
                    raise ValueError
                if min(x1, y1, x2, y2) < 0 or x2 <= x1 or y2 <= y1:
                    raise ValueError
            except (TypeError, ValueError):
                errors["bbox"] = "bbox must contain four increasing non-negative coordinates."
        if errors:
            raise ValidationError(errors)

class ObservationMatch(models.Model):
    observation_a = models.ForeignKey(DamageObservation, on_delete=models.CASCADE, related_name="matches_as_a")
    observation_b = models.ForeignKey(DamageObservation, on_delete=models.CASCADE, related_name="matches_as_b")
    score = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    method = models.CharField(max_length=100)
    decision = models.CharField(max_length=24, choices=[
        ("same_damage", "Same damage"), ("different_damage", "Different damage"), ("uncertain", "Uncertain")
    ], default="uncertain")
    evidence = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["observation_a", "observation_b", "method"],
            name="uniq_routiq_observation_match",
        )]

    def clean(self):
        if self.observation_a_id and self.observation_a_id == self.observation_b_id:
            raise ValidationError("An observation cannot match itself.")

class DamageStatusAssessment(models.Model):
    damage_instance = models.ForeignKey(DamageInstance, on_delete=models.CASCADE, related_name="assessments")
    status = models.CharField(max_length=32, choices=[
        x for x in DAMAGE_STATUSES if x[0] != "unknown"
    ])
    confidence = models.FloatField(default=0, validators=[MinValueValidator(0), MaxValueValidator(1)])
    rationale = models.TextField(blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    independently_verified = models.BooleanField(default=False)
    assessed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class SessionEvidenceComparison(models.Model):
    """Persisted visual evidence comparison between two private inspection sessions."""
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="session_evidence_comparisons",
    )
    session_a = models.ForeignKey(
        InspectionSession,
        on_delete=models.PROTECT,
        related_name="visual_comparisons_as_a",
    )
    session_b = models.ForeignKey(
        InspectionSession,
        on_delete=models.PROTECT,
        related_name="visual_comparisons_as_b",
    )
    method = models.CharField(max_length=80, default="orb_homography_ssim_v1")
    status = models.CharField(max_length=40, default="insufficient_evidence")
    evidence = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(
            fields=["session_a", "session_b", "method"],
            name="uniq_routiq_session_visual_pair",
        )]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.session_a_id and self.session_a_id == self.session_b_id:
            raise ValidationError("An inspection session cannot be compared with itself.")
        if self.session_a_id and self.session_b_id:
            owner_a = self.session_a.owner_id
            owner_b = self.session_b.owner_id
            if owner_a != owner_b or (self.owner_id and self.owner_id != owner_a):
                raise ValidationError("Both sessions must belong to the same owner.")
