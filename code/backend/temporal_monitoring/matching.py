"""Spatial comparison helpers for repeat road-damage observations."""
from __future__ import annotations
import math

EARTH_RADIUS_METERS = 6_371_008.8


def haversine_distance_m(lat_a, lon_a, lat_b, lon_b):
    """Return great-circle separation in meters for decimal degree coordinates."""
    values = [float(lat_a), float(lon_a), float(lat_b), float(lon_b)]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Coordinates must be finite numbers.")
    if not (-90 <= values[0] <= 90 and -90 <= values[2] <= 90):
        raise ValueError("Latitude must be between -90 and 90.")
    if not (-180 <= values[1] <= 180 and -180 <= values[3] <= 180):
        raise ValueError("Longitude must be between -180 and 180.")
    lat1, lon1, lat2, lon2 = map(math.radians, values)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(min(1.0, max(0.0, a))))
