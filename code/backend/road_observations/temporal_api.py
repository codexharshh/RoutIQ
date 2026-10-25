"""Authenticated endpoint for auditable repeat-pass evidence comparison."""
import math
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from temporal_monitoring.status_assessment import compare_observations
from .models import DamageObservation, ObservationMatch, InspectionSession, SessionEvidenceComparison
from .image_comparison import compare_session_images


class TemporalReviewInputSerializer(serializers.Serializer):
    observation_a_id = serializers.IntegerField(min_value=1)
    observation_b_id = serializers.IntegerField(min_value=1)
    distance_threshold_m = serializers.FloatField(required=False, default=15.0, min_value=3.0, max_value=100.0)

    def validate(self, attrs):
        if attrs["observation_a_id"] == attrs["observation_b_id"]:
            raise serializers.ValidationError("Choose two different observations.")
        if not math.isfinite(attrs["distance_threshold_m"]):
            raise serializers.ValidationError({"distance_threshold_m": "Enter a finite distance threshold."})
        return attrs


class TemporalEvidenceReviewView(APIView):
    permission_classes = [IsAuthenticated]
    method_name = "quality_aware_repeat_pass_v1"

    def post(self, request):
        serializer = TemporalReviewInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        owner_scope = {"session__owner": request.user}
        observation_a = get_object_or_404(
            DamageObservation.objects.select_related("session", "instance"),
            pk=values["observation_a_id"], **owner_scope,
        )
        observation_b = get_object_or_404(
            DamageObservation.objects.select_related("session", "instance"),
            pk=values["observation_b_id"], **owner_scope,
        )
        # Canonical ordering avoids duplicate pairs when users reverse the selectors.
        if observation_a.pk > observation_b.pk:
            observation_a, observation_b = observation_b, observation_a

        result = compare_observations(
            observation_a, observation_b,
            distance_threshold_m=values["distance_threshold_m"],
        )
        evidence = {
            **result,
            "method": self.method_name,
            "distance_threshold_m": float(values["distance_threshold_m"]),
            "repair_verification": "not_inferred",
        }
        with transaction.atomic():
            match, created = ObservationMatch.objects.update_or_create(
                observation_a=observation_a,
                observation_b=observation_b,
                method=self.method_name,
                defaults={
                    "score": result["score"],
                    "decision": result["decision"],
                    "evidence": evidence,
                },
            )

        return Response({
            "match_id": match.pk,
            "created": created,
            "observation_a_id": observation_a.pk,
            "observation_b_id": observation_b.pk,
            **result,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

class SessionEvidenceComparisonInputSerializer(serializers.Serializer):
    session_a_id = serializers.IntegerField(min_value=1)
    session_b_id = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        if attrs["session_a_id"] == attrs["session_b_id"]:
            raise serializers.ValidationError("Choose two different inspection sessions.")
        return attrs


class SessionEvidenceComparisonView(APIView):
    """Compare two private inspection images and save a review-only visual result."""
    permission_classes = [IsAuthenticated]
    method_name = "orb_homography_ssim_v1"

    def post(self, request):
        serializer = SessionEvidenceComparisonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        owner_scope = {"owner": request.user}
        session_a = get_object_or_404(InspectionSession.objects.all(), pk=values["session_a_id"], **owner_scope)
        session_b = get_object_or_404(InspectionSession.objects.all(), pk=values["session_b_id"], **owner_scope)

        # The reference session is always older than the comparison session.
        if (session_a.created_at, session_a.pk) > (session_b.created_at, session_b.pk):
            session_a, session_b = session_b, session_a

        image_comparison = compare_session_images(session_a, session_b)
        detections_a = session_a.observations.count()
        detections_b = session_b.observations.count()
        evidence = {
            "method": self.method_name,
            "session_a_id": session_a.pk,
            "session_b_id": session_b.pk,
            "detections_a": detections_a,
            "detections_b": detections_b,
            "image_comparison": image_comparison,
            "repair_verification": "not_inferred",
        }
        with transaction.atomic():
            comparison, created = SessionEvidenceComparison.objects.update_or_create(
                session_a=session_a,
                session_b=session_b,
                method=self.method_name,
                defaults={
                    "owner": request.user,
                    "status": image_comparison["status"],
                    "evidence": evidence,
                },
            )

        return Response({
            "comparison_id": comparison.pk,
            "created": created,
            "session_a_id": session_a.pk,
            "session_b_id": session_b.pk,
            "session_a_title": session_a.title,
            "session_b_title": session_b.title,
            "detections_a": detections_a,
            "detections_b": detections_b,
            "image_comparison": image_comparison,
            "repair_verification": "not_inferred",
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
