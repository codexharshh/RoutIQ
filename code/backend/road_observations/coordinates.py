"""Coordinate validation and photo GPS metadata helpers."""
from decimal import Decimal, InvalidOperation


def parse_coordinate_pair(latitude, longitude):
    """Return finite WGS-84 decimal coordinates or raise ValueError."""
    if latitude in (None, "") or longitude in (None, ""):
        raise ValueError("Provide both latitude and longitude.")
    try:
        latitude_value = Decimal(str(latitude))
        longitude_value = Decimal(str(longitude))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Latitude and longitude must be numeric.") from exc
    if not latitude_value.is_finite() or not longitude_value.is_finite():
        raise ValueError("Latitude and longitude must be finite numbers.")
    if not -90 <= latitude_value <= 90 or not -180 <= longitude_value <= 180:
        raise ValueError("Coordinates are out of range: latitude -90 to 90 and longitude -180 to 180.")
    return latitude_value, longitude_value


def _as_float(value):
    """Convert a Pillow EXIF rational value to a finite float."""
    if isinstance(value, (tuple, list)) and len(value) == 2:
        numerator, denominator = value
        if float(denominator) == 0:
            raise ValueError("Invalid GPS rational value.")
        value = float(numerator) / float(denominator)
    result = float(value)
    if result != result or abs(result) == float("inf"):
        raise ValueError("GPS metadata contains a non-finite value.")
    return result


def extract_photo_gps(image):
    """Extract WGS-84 GPS coordinates and optional accuracy from a Pillow image.

    Returns ``(latitude, longitude, accuracy_m)`` or ``None`` when GPS metadata
    is absent or malformed. The caller records the provenance as ``photo_exif``.
    """
    try:
        gps = image.getexif().get_ifd(34853)
        if not gps:
            return None

        def dms_to_degrees(values, reference, positive, negative):
            if len(values) != 3 or reference not in (positive, negative):
                raise ValueError("Malformed GPS metadata.")
            degrees, minutes, seconds = (_as_float(value) for value in values)
            if degrees < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
                raise ValueError("Malformed GPS metadata.")
            coordinate = degrees + minutes / 60 + seconds / 3600
            return -coordinate if reference == negative else coordinate

        latitude_ref = gps.get(1)
        longitude_ref = gps.get(3)
        if isinstance(latitude_ref, bytes):
            latitude_ref = latitude_ref.decode("ascii", errors="strict")
        if isinstance(longitude_ref, bytes):
            longitude_ref = longitude_ref.decode("ascii", errors="strict")
        latitude = dms_to_degrees(gps[2], latitude_ref, "N", "S")
        longitude = dms_to_degrees(gps[4], longitude_ref, "E", "W")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            return None

        accuracy = None
        if 31 in gps:
            accuracy = _as_float(gps[31])
            if accuracy < 0:
                return None
        return Decimal(str(latitude)), Decimal(str(longitude)), accuracy
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError, ZeroDivisionError):
        return None
