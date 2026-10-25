/**
 * RoutIQ - GPS Location and Metadata Extraction Service
 *
 * Provides safe device geolocation capture with accuracy reporting,
 * EXIF GPS metadata extraction from road inspection images, and
 * strict coordinate validation (-90..90, -180..180).
 */

export interface GpsCoordinates {
  latitude: number;
  longitude: number;
  accuracyM?: number;
}

export interface CoordinateValidationResult {
  valid: boolean;
  latitude?: number;
  longitude?: number;
  error?: string;
}

/**
 * Validate WGS-84 coordinate pair within valid geographical boundaries.
 */
export function validateCoordinates(
  latInput: number | string | null | undefined,
  lonInput: number | string | null | undefined
): CoordinateValidationResult {
  const latStr = latInput !== null && latInput !== undefined ? String(latInput).trim() : '';
  const lonStr = lonInput !== null && lonInput !== undefined ? String(lonInput).trim() : '';

  if (!latStr || !lonStr) {
    return { valid: false, error: 'Enter both latitude and longitude.' };
  }

  const latitude = Number(latStr);
  const longitude = Number(lonStr);

  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    return { valid: false, error: 'Coordinates must be valid finite numbers.' };
  }

  if (latitude < -90 || latitude > 90) {
    return { valid: false, error: 'Latitude must be between -90 and 90 degrees.' };
  }

  if (longitude < -180 || longitude > 180) {
    return { valid: false, error: 'Longitude must be between -180 and 180 degrees.' };
  }

  return {
    valid: true,
    latitude: Number(latitude.toFixed(7)),
    longitude: Number(longitude.toFixed(7)),
  };
}

/**
 * Format browser GeolocationPositionError into clear, user-friendly guidance.
 */
export function getGeolocationErrorMessage(
  error: { code?: number; message?: string } | null | undefined
): string {
  if (!error) return 'Unable to retrieve your current location. Please enter coordinates manually.';

  switch (error.code) {
    case 1: // GeolocationPositionError.PERMISSION_DENIED
      return 'Location permission was denied. You can still enter coordinates manually.';
    case 2: // GeolocationPositionError.POSITION_UNAVAILABLE
      return 'Location information is currently unavailable. Please enter coordinates manually.';
    case 3: // GeolocationPositionError.TIMEOUT
      return 'Location request timed out. Please try again or enter coordinates manually.';
    default:
      return error.message && error.message.trim()
        ? `Location error: ${error.message}. Please enter coordinates manually.`
        : 'Unable to acquire device location. Please enter coordinates manually.';
  }
}

/**
 * Acquire device's current location via browser Geolocation API with high accuracy.
 * Only invoked upon explicit user interaction.
 */
export async function getCurrentDeviceLocation(
  options?: PositionOptions
): Promise<{ latitude: number; longitude: number; accuracy: number }> {
  if (typeof navigator === 'undefined' || !navigator.geolocation) {
    throw new Error('Geolocation is not supported by your browser. Please enter coordinates manually.');
  }

  const defaultOptions: PositionOptions = {
    enableHighAccuracy: true,
    timeout: 10000,
    maximumAge: 0,
    ...options,
  };

  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude, accuracy } = position.coords;
        const validation = validateCoordinates(latitude, longitude);
        if (!validation.valid || validation.latitude === undefined || validation.longitude === undefined) {
          reject(new Error(validation.error || 'Device returned invalid coordinates.'));
          return;
        }

        resolve({
          latitude: validation.latitude,
          longitude: validation.longitude,
          accuracy: Number.isFinite(accuracy) && accuracy >= 0 ? Number(accuracy.toFixed(1)) : 0,
        });
      },
      (error) => {
        reject(new Error(getGeolocationErrorMessage(error)));
      },
      defaultOptions
    );
  });
}

/**
 * Parse EXIF GPS metadata from an ArrayBuffer of a JPEG image.
 * Safely parses TIFF header, IFD0, and GPSInfo sub-IFD without external libraries.
 */
export function extractExifGpsFromBuffer(buffer: ArrayBuffer): GpsCoordinates | null {
  try {
    const view = new DataView(buffer);
    if (view.byteLength < 4) return null;

    // Verify JPEG SOI (0xFFD8)
    if (view.getUint16(0) !== 0xFFD8) return null;

    let offset = 2;
    let exifOffset = -1;

    while (offset < view.byteLength - 4) {
      const marker = view.getUint16(offset);
      offset += 2;

      if (marker === 0xFFE1) { // APP1 marker
        const length = view.getUint16(offset);
        // Verify 'Exif\0\0' header
        if (
          view.byteLength >= offset + 8 &&
          view.getUint8(offset + 2) === 0x45 && // E
          view.getUint8(offset + 3) === 0x78 && // x
          view.getUint8(offset + 4) === 0x69 && // i
          view.getUint8(offset + 5) === 0x66 && // f
          view.getUint8(offset + 6) === 0x00 &&
          view.getUint8(offset + 7) === 0x00
        ) {
          exifOffset = offset + 8;
          break;
        }
        offset += length;
      } else if ((marker & 0xFF00) === 0xFF00) {
        if (marker === 0xFFDA || marker === 0xFFD9) break; // SOS or EOI
        const length = view.getUint16(offset);
        offset += length;
      } else {
        break;
      }
    }

    if (exifOffset === -1 || exifOffset + 8 > view.byteLength) return null;

    // Read TIFF header endianness
    const endianness = view.getUint16(exifOffset);
    let littleEndian = false;
    if (endianness === 0x4949) { // 'II' - Intel little endian
      littleEndian = true;
    } else if (endianness === 0x4D4D) { // 'MM' - Motorola big endian
      littleEndian = false;
    } else {
      return null;
    }

    // Verify TIFF magic number 42 (0x002A)
    if (view.getUint16(exifOffset + 2, littleEndian) !== 0x002A) return null;

    const ifd0Offset = view.getUint32(exifOffset + 4, littleEndian);
    if (exifOffset + ifd0Offset + 2 > view.byteLength) return null;

    // Traverse IFD0 to locate GPSInfo tag (0x8825)
    let gpsIfdOffset = -1;
    const ifd0Entries = view.getUint16(exifOffset + ifd0Offset, littleEndian);
    let currentEntryOffset = exifOffset + ifd0Offset + 2;

    for (let i = 0; i < ifd0Entries; i++) {
      if (currentEntryOffset + 12 > view.byteLength) break;
      const tag = view.getUint16(currentEntryOffset, littleEndian);
      if (tag === 0x8825) { // GPSInfo tag
        gpsIfdOffset = view.getUint32(currentEntryOffset + 8, littleEndian);
        break;
      }
      currentEntryOffset += 12;
    }

    if (gpsIfdOffset === -1 || exifOffset + gpsIfdOffset + 2 > view.byteLength) return null;

    const gpsEntries = view.getUint16(exifOffset + gpsIfdOffset, littleEndian);
    let gpsEntryOffset = exifOffset + gpsIfdOffset + 2;

    let latRef: string | null = null;
    let lonRef: string | null = null;
    let latValues: number[] | null = null;
    let lonValues: number[] | null = null;
    let accuracyM: number | undefined = undefined;

    const readRational = (valOffset: number): number | null => {
      if (exifOffset + valOffset + 8 > view.byteLength) return null;
      const num = view.getUint32(exifOffset + valOffset, littleEndian);
      const den = view.getUint32(exifOffset + valOffset + 4, littleEndian);
      if (den === 0) return null;
      return num / den;
    };

    const readRationals = (valOffset: number, count: number): number[] | null => {
      const res: number[] = [];
      for (let i = 0; i < count; i++) {
        const val = readRational(valOffset + i * 8);
        if (val === null) return null;
        res.push(val);
      }
      return res;
    };

    for (let i = 0; i < gpsEntries; i++) {
      if (gpsEntryOffset + 12 > view.byteLength) break;
      const tag = view.getUint16(gpsEntryOffset, littleEndian);
      const type = view.getUint16(gpsEntryOffset + 2, littleEndian);

      if (tag === 1) { // GPSLatitudeRef
        latRef = String.fromCharCode(view.getUint8(gpsEntryOffset + 8));
      } else if (tag === 2) { // GPSLatitude
        const valOffset = view.getUint32(gpsEntryOffset + 8, littleEndian);
        latValues = readRationals(valOffset, 3);
      } else if (tag === 3) { // GPSLongitudeRef
        lonRef = String.fromCharCode(view.getUint8(gpsEntryOffset + 8));
      } else if (tag === 4) { // GPSLongitude
        const valOffset = view.getUint32(gpsEntryOffset + 8, littleEndian);
        lonValues = readRationals(valOffset, 3);
      } else if (tag === 31) { // GPSHPositioningError (accuracy)
        if (type === 5 || type === 10) { // Rational
          const valOffset = view.getUint32(gpsEntryOffset + 8, littleEndian);
          const r = readRational(valOffset);
          if (r !== null && Number.isFinite(r) && r >= 0) accuracyM = Number(r.toFixed(1));
        } else if (type === 11) { // Float
          const f = view.getFloat32(gpsEntryOffset + 8, littleEndian);
          if (Number.isFinite(f) && f >= 0) accuracyM = Number(f.toFixed(1));
        } else if (type === 12) { // Double
          const valOffset = view.getUint32(gpsEntryOffset + 8, littleEndian);
          if (exifOffset + valOffset + 8 <= view.byteLength) {
            const d = view.getFloat64(exifOffset + valOffset, littleEndian);
            if (Number.isFinite(d) && d >= 0) accuracyM = Number(d.toFixed(1));
          }
        }
      }
      gpsEntryOffset += 12;
    }

    if (!latRef || !lonRef || !latValues || !lonValues) return null;
    if (!['N', 'S'].includes(latRef) || !['E', 'W'].includes(lonRef)) return null;

    const [latD, latM, latS] = latValues;
    const [lonD, lonM, lonS] = lonValues;

    if (latD < 0 || latM < 0 || latM >= 60 || latS < 0 || latS >= 60) return null;
    if (lonD < 0 || lonM < 0 || lonM >= 60 || lonS < 0 || lonS >= 60) return null;

    let latitude = latD + latM / 60 + latS / 3600;
    if (latRef === 'S') latitude = -latitude;

    let longitude = lonD + lonM / 60 + lonS / 3600;
    if (lonRef === 'W') longitude = -longitude;

    const validation = validateCoordinates(latitude, longitude);
    if (!validation.valid || validation.latitude === undefined || validation.longitude === undefined) {
      return null;
    }

    return {
      latitude: validation.latitude,
      longitude: validation.longitude,
      accuracyM,
    };
  } catch {
    return null;
  }
}

/**
 * Safely extract EXIF GPS metadata from a File or Blob.
 */
export async function extractExifGps(file: File | Blob): Promise<GpsCoordinates | null> {
  if (!file || typeof file.slice !== 'function') return null;

  try {
    // Read first 128KB which contains the EXIF header block
    const slice = file.slice(0, 131072);
    const buffer = await slice.arrayBuffer();
    return extractExifGpsFromBuffer(buffer);
  } catch {
    return null;
  }
}
