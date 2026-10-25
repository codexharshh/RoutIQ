from rest_framework import serializers
from .models import Pothole


class PotholeFrameSerializer(serializers.ModelSerializer):
    """Serializer for frame data only."""
    class Meta:
        model = Pothole
        fields = ["id", "frame_number", "frame_image"]


class PotholeSerializer(serializers.ModelSerializer):
    """Serializer for Pothole model with full CRUD operations."""
    location_string = serializers.ReadOnlyField()

    class Meta:
        model = Pothole
        fields = [
            "id", "latitude", "longitude", "location_string", "num_potholes",
            "status", "severity", "source", "image", "frame_image",
            "frame_number", "timestamp", "created_at", "updated_at",
            "description", "road_c_date", "contractor",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "location_string", "source"]


class PotholeListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing potholes without large frame payloads."""
    location_string = serializers.ReadOnlyField()

    class Meta:
        model = Pothole
        fields = [
            "id", "latitude", "longitude", "location_string", "num_potholes",
            "status", "severity", "source", "timestamp", "image", "frame_image",
            "frame_number", "road_c_date", "contractor", "description",
        ]
        read_only_fields = ["source"]


class PotholeCreateSerializer(serializers.ModelSerializer):
    """Create citizen/manual reports without allowing client-set status or provenance."""

    class Meta:
        model = Pothole
        fields = [
            "latitude", "longitude", "num_potholes", "status", "severity",
            "source", "description", "image", "road_c_date", "contractor",
        ]
        read_only_fields = ["status", "severity", "source"]

    def validate_latitude(self, value):
        if not -90 <= value <= 90:
            raise serializers.ValidationError("Latitude must be between -90 and 90 degrees.")
        return value

    def validate_longitude(self, value):
        if not -180 <= value <= 180:
            raise serializers.ValidationError("Longitude must be between -180 and 180 degrees.")
        return value

    def validate_num_potholes(self, value):
        if value < 1:
            raise serializers.ValidationError("Number of potholes must be at least 1.")
        if value > 100:
            raise serializers.ValidationError("Number of potholes seems unreasonably high. Please verify.")
        return value


class PotholeUpdateSerializer(serializers.ModelSerializer):
    """Update a pothole report; object-level permissions restrict this to staff."""

    class Meta:
        model = Pothole
        fields = [
            "num_potholes", "status", "severity", "description", "image",
            "road_c_date", "contractor", "source",
        ]
        read_only_fields = ["source"]

    def validate_num_potholes(self, value):
        if value < 1:
            raise serializers.ValidationError("Number of potholes must be at least 1.")
        if value > 100:
            raise serializers.ValidationError("Number of potholes seems unreasonably high. Please verify.")
        return value
