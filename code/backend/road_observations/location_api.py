"""Owner-scoped endpoint for correcting/adding GPS to a saved RoutIQ observation."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DamageObservation
from .coordinates import parse_coordinate_pair


class ObservationLocationUpdateView(APIView):
    """Allow an observation owner to add/update its photo coordinates."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        observation = get_object_or_404(
            DamageObservation.objects.select_related("instance"),
            pk=pk,
            session__owner=request.user,
        )

        try:
            latitude, longitude = parse_coordinate_pair(
                request.data.get("latitude"), request.data.get("longitude")
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        coordinate_source = request.data.get("coordinate_source", "manual")
        if coordinate_source not in {"manual", "device_current"}:
            return Response({"detail": "Coordinate updates must use manual or device_current provenance."},
                            status=status.HTTP_400_BAD_REQUEST)
        raw_accuracy = request.data.get("gps_accuracy_m")
        if raw_accuracy in (None, ""):
            gps_accuracy_m = None
        else:
            try:
                gps_accuracy_m = float(raw_accuracy)
            except (TypeError, ValueError):
                return Response({"detail": "GPS accuracy must be a non-negative number."},
                                status=status.HTTP_400_BAD_REQUEST)
            if not 0 <= gps_accuracy_m < float("inf"):
                return Response({"detail": "GPS accuracy must be a finite non-negative number."},
                                status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            observation.latitude = latitude
            observation.longitude = longitude
            observation.gps_accuracy_m = gps_accuracy_m
            observation.metadata = {**(observation.metadata or {}), "coordinate_source": coordinate_source}
            observation.save(update_fields=["latitude", "longitude", "gps_accuracy_m", "metadata"])

            if observation.instance_id:
                instance = observation.instance
                instance.latitude = latitude
                instance.longitude = longitude
                instance.save(update_fields=["latitude", "longitude", "updated_at"])

        return Response({
            "id": observation.pk,
            "latitude": float(observation.latitude),
            "longitude": float(observation.longitude),
            "coordinate_source": coordinate_source,
            "gps_accuracy_m": observation.gps_accuracy_m,
            "map_ready": True,
            "detail": "Photo coordinates saved. The observation is now eligible for the map overlay.",
        }, status=status.HTTP_200_OK)
