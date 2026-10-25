from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from ..models import DamageInstance, DamageObservation

@transaction.atomic
def create_observation(*, owner, validated_data, trusted_detector_output=False):
    session = validated_data["session"]
    if session.owner_id != owner.id:
        raise PermissionDenied("Inspection session does not belong to this user.")

    key = validated_data.get("idempotency_key")
    if key:
        existing = DamageObservation.objects.filter(session=session, idempotency_key=key).first()
        if existing:
            return existing, False

    instance = validated_data.get("instance")
    if instance and instance.created_by_id not in (None, owner.id):
        raise PermissionDenied("Damage instance does not belong to this user.")

    # Only trusted internal detector ingestion may preserve prediction evidence.
    # Generic API writes always receive manual provenance, regardless of client input.
    if trusted_detector_output:
        observed_at = validated_data.get("observed_at") or timezone.now()
        validated_data["observed_at"] = observed_at
        metadata = dict(validated_data.get("metadata") or {})
        metadata["observation_source"] = "model_inference"
        validated_data["metadata"] = metadata
    else:
        observed_at = validated_data.get("observed_at") or timezone.now()
        validated_data["observed_at"] = observed_at
        validated_data.setdefault("confidence", 0.0)
        validated_data["class_id"] = None
        validated_data["bbox"] = None
        validated_data["model_name"] = ""
        validated_data["model_version"] = ""
        validated_data["source_name"] = "manual-api-report"
        metadata = dict(validated_data.get("metadata") or {})
        metadata["observation_source"] = "manual"
        validated_data["metadata"] = metadata
    if instance is None:
        instance = DamageInstance.objects.create(
            created_by=owner,
            damage_class=validated_data["damage_class"],
            latitude=validated_data.get("latitude"),
            longitude=validated_data.get("longitude"),
            first_seen_at=observed_at,
            last_seen_at=observed_at,
        )
        validated_data["instance"] = instance
    else:
        instance.current_status = "damage_persists"
        if instance.first_seen_at is None or observed_at < instance.first_seen_at:
            instance.first_seen_at = observed_at
        if instance.last_seen_at is None or observed_at > instance.last_seen_at:
            instance.last_seen_at = observed_at
        instance.save(update_fields=["current_status", "first_seen_at", "last_seen_at", "updated_at"])

    return DamageObservation.objects.create(**validated_data), True
