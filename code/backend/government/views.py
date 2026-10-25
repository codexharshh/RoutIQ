import logging

from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, authentication_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser

from .models import GovUser, RoadSegment
from .serializers import (
    GovUserSerializer,
    GovUserCreateSerializer,
    GovAuthSerializer,
    RoadSegmentSerializer,
    RoadSegmentCreateSerializer,
)
from .authentication import GovTokenAuthentication, issue_gov_token
from routiq_config.throttles import GovernmentLoginThrottle

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAdminUser])
def gov_signup(request):
    """Create government accounts only through an authenticated Django staff account."""
    serializer = GovUserCreateSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response({
            "user": GovUserSerializer(user).data,
            "message": "Government account created successfully.",
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([GovernmentLoginThrottle])
def gov_login(request):
    """Authenticate a government user and return a signed, expiring bearer token."""
    serializer = GovAuthSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.validated_data["user"]
    try:
        token = issue_gov_token(user)
    except ValueError:
        return Response({"detail": "Government account is unavailable."},
                        status=status.HTTP_401_UNAUTHORIZED)

    return Response({
        "user": GovUserSerializer(user).data,
        "token": token,
        "expires_in": 3600,
        "message": "Successfully logged in",
    }, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([GovTokenAuthentication])
@permission_classes([IsAuthenticated])
def gov_logout(request):
    """Tell the client to discard its short-lived stateless token."""
    return Response({
        "message": "Logged out. Discard the bearer token; it expires within one hour."
    }, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([GovTokenAuthentication])
@permission_classes([IsAuthenticated])
def verify_token(request):
    """Verify a signed government bearer token."""
    return Response({
        "valid": True,
        "user": GovUserSerializer(request.user).data,
    }, status=status.HTTP_200_OK)


class RoadSegmentViewSet(viewsets.ModelViewSet):
    """Publicly readable road-segment data with government-token-protected writes."""

    authentication_classes = [GovTokenAuthentication]

    def get_permissions(self):
        # Road geometry is used by the public map; modifications require a government token.
        permission = AllowAny if self.action in {"list", "retrieve"} else IsAuthenticated
        return [permission()]

    def get_queryset(self):
        return RoadSegment.objects.using("government").all()

    def get_serializer_class(self):
        if self.action == "create":
            return RoadSegmentCreateSerializer
        return RoadSegmentSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        road_segment = serializer.save(created_by=request.user)

        try:
            self.update_road_health_after_segment_creation()
        except Exception:
            logger.exception("Failed to update road health after segment creation")

        response_serializer = RoadSegmentSerializer(road_segment)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def update_road_health_after_segment_creation(self):
        """Refresh road-health values after creating a road segment."""
        from potholes.road_health_views import RoadHealthViewSet

        viewset = RoadHealthViewSet()
        updated_count = viewset.update_road_health_data()
        logger.info("Road health updated for %s segments after road-segment creation", updated_count)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete(using="government")
        return Response(status=status.HTTP_204_NO_CONTENT)
