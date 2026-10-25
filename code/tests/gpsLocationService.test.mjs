import assert from 'node:assert/strict';
import test from 'node:test';
import {
  validateCoordinates,
  getGeolocationErrorMessage,
  getCurrentDeviceLocation,
  extractExifGpsFromBuffer,
} from '../src/services/gpsLocationService.ts';

test('validateCoordinates: accepts valid coordinates within boundaries', () => {
  const cases = [
    { lat: 20.2961, lon: 85.8245, expectedLat: 20.2961, expectedLon: 85.8245 },
    { lat: '28.6139', lon: '77.2090', expectedLat: 28.6139, expectedLon: 77.209 },
    { lat: 90, lon: 180, expectedLat: 90, expectedLon: 180 },
    { lat: -90, lon: -180, expectedLat: -90, expectedLon: -180 },
    { lat: 0, lon: 0, expectedLat: 0, expectedLon: 0 },
  ];

  for (const c of cases) {
    const res = validateCoordinates(c.lat, c.lon);
    assert.equal(res.valid, true);
    assert.equal(res.latitude, c.expectedLat);
    assert.equal(res.longitude, c.expectedLon);
  }
});

test('validateCoordinates: rejects missing or empty coordinates', () => {
  assert.equal(validateCoordinates('', '77.2').valid, false);
  assert.equal(validateCoordinates('28.6', '').valid, false);
  assert.equal(validateCoordinates(null, '77.2').valid, false);
  assert.equal(validateCoordinates('28.6', undefined).valid, false);
  assert.match(validateCoordinates('', '').error ?? '', /both latitude and longitude/i);
});

test('validateCoordinates: rejects non-numeric and non-finite values', () => {
  assert.equal(validateCoordinates('abc', '77.2').valid, false);
  assert.equal(validateCoordinates('28.6', 'xyz').valid, false);
  assert.equal(validateCoordinates(NaN, 77.2).valid, false);
  assert.equal(validateCoordinates(28.6, Infinity).valid, false);
  assert.match(validateCoordinates('abc', 'xyz').error ?? '', /finite/i);
});

test('validateCoordinates: rejects out-of-range latitude and longitude', () => {
  const latHigh = validateCoordinates(90.1, 77.2);
  assert.equal(latHigh.valid, false);
  assert.match(latHigh.error ?? '', /Latitude must be between -90 and 90/i);

  const latLow = validateCoordinates(-90.1, 77.2);
  assert.equal(latLow.valid, false);
  assert.match(latLow.error ?? '', /Latitude must be between -90 and 90/i);

  const lonHigh = validateCoordinates(28.6, 180.1);
  assert.equal(lonHigh.valid, false);
  assert.match(lonHigh.error ?? '', /Longitude must be between -180 and 180/i);

  const lonLow = validateCoordinates(28.6, -180.1);
  assert.equal(lonLow.valid, false);
  assert.match(lonLow.error ?? '', /Longitude must be between -180 and 180/i);
});

test('getGeolocationErrorMessage: provides distinct, actionable messages', () => {
  assert.match(getGeolocationErrorMessage({ code: 1, message: 'denied' }), /permission was denied.*manually/i);
  assert.match(getGeolocationErrorMessage({ code: 2, message: 'unavailable' }), /unavailable.*manually/i);
  assert.match(getGeolocationErrorMessage({ code: 3, message: 'timeout' }), /timed out.*manually/i);
  assert.match(getGeolocationErrorMessage({ code: 99, message: 'other' }), /other/i);
});

test('getCurrentDeviceLocation: handles unsupported browser environments', async () => {
  const originalNavigator = globalThis.navigator;
  try {
    // @ts-expect-error test override
    delete globalThis.navigator;
    await assert.rejects(
      async () => getCurrentDeviceLocation(),
      /not supported by your browser/i
    );
  } finally {
    globalThis.navigator = originalNavigator;
  }
});

test('getCurrentDeviceLocation: successful location acquisition fills coordinates and accuracy', async () => {
  const originalNavigator = globalThis.navigator;
  try {
    globalThis.navigator = {
      geolocation: {
        getCurrentPosition(success) {
          success({
            coords: {
              latitude: 20.2961,
              longitude: 85.8245,
              accuracy: 12.4,
              altitude: null,
              altitudeAccuracy: null,
              heading: null,
              speed: null,
            },
            timestamp: Date.now(),
          });
        },
      },
    };

    const location = await getCurrentDeviceLocation();
    assert.equal(location.latitude, 20.2961);
    assert.equal(location.longitude, 85.8245);
    assert.equal(location.accuracy, 12.4);
  } finally {
    globalThis.navigator = originalNavigator;
  }
});

test('getCurrentDeviceLocation: permission denial does not crash and provides clear error', async () => {
  const originalNavigator = globalThis.navigator;
  try {
    globalThis.navigator = {
      geolocation: {
        getCurrentPosition(_success, error) {
          error({
            code: 1,
            message: 'User denied Geolocation',
            PERMISSION_DENIED: 1,
            POSITION_UNAVAILABLE: 2,
            TIMEOUT: 3,
          });
        },
      },
    };

    await assert.rejects(
      async () => getCurrentDeviceLocation(),
      /permission was denied/i
    );

    // Verify manual fallback remains usable when permission is denied
    const manualResult = validateCoordinates('20.2961', '85.8245');
    assert.equal(manualResult.valid, true);
    assert.equal(manualResult.latitude, 20.2961);
  } finally {
    globalThis.navigator = originalNavigator;
  }
});

test('getCurrentDeviceLocation: timeout error reporting', async () => {
  const originalNavigator = globalThis.navigator;
  try {
    globalThis.navigator = {
      geolocation: {
        getCurrentPosition(_success, error) {
          error({
            code: 3,
            message: 'Timeout expired',
            PERMISSION_DENIED: 1,
            POSITION_UNAVAILABLE: 2,
            TIMEOUT: 3,
          });
        },
      },
    };

    await assert.rejects(
      async () => getCurrentDeviceLocation(),
      /timed out/i
    );
  } finally {
    globalThis.navigator = originalNavigator;
  }
});

test('extractExifGpsFromBuffer: safely handles non-JPEG or truncated buffers', () => {
  assert.equal(extractExifGpsFromBuffer(new ArrayBuffer(0)), null);
  assert.equal(extractExifGpsFromBuffer(new Uint8Array([0x00, 0x01, 0x02, 0x03]).buffer), null);
  // JPEG SOI without APP1/EXIF
  assert.equal(extractExifGpsFromBuffer(new Uint8Array([0xFF, 0xD8, 0xFF, 0xD9]).buffer), null);
});

test('extractExifGpsFromBuffer: parses valid JPEG with GPS metadata', () => {
  // Construct minimal valid JPEG with EXIF GPS Info
  // SOI (2) + APP1 marker (2) + length (2) + 'Exif\0\0' (6) + TIFF header (8) + IFD0 (2+12+4) + GPS IFD ...
  const buf = new Uint8Array(256);
  const view = new DataView(buf.buffer);

  // JPEG SOI
  view.setUint16(0, 0xFFD8);
  // APP1
  view.setUint16(2, 0xFFE1);
  // APP1 length
  view.setUint16(4, 250);
  // 'Exif\0\0'
  buf[6] = 0x45; buf[7] = 0x78; buf[8] = 0x69; buf[9] = 0x66; buf[10] = 0x00; buf[11] = 0x00;

  // TIFF header at offset 12 (exifOffset = 12)
  // 'II' (0x4949) little-endian
  view.setUint16(12, 0x4949);
  // Magic 42
  view.setUint16(14, 0x002A, true);
  // IFD0 offset relative to exifOffset = 8
  view.setUint32(16, 8, true);

  // IFD0 at offset 20: 1 entry
  view.setUint16(20, 1, true);
  // Tag 0x8825 (GPSInfo)
  view.setUint16(22, 0x8825, true);
  view.setUint16(24, 4, true); // LONG
  view.setUint32(26, 1, true); // count
  // Value offset relative to exifOffset = 26 (offset 38)
  view.setUint32(30, 26, true);
  // Next IFD offset = 0
  view.setUint32(34, 0, true);

  // GPS IFD at offset 38: 4 entries
  view.setUint16(38, 4, true);

  // Entry 1: tag 1 (latRef = 'N')
  view.setUint16(40, 1, true);
  view.setUint16(42, 2, true); // ASCII
  view.setUint32(44, 2, true);
  buf[48] = 0x4E; buf[49] = 0x00; // 'N\0'

  // Entry 2: tag 2 (lat = 28 deg, 36 min, 50 sec)
  view.setUint16(52, 2, true);
  view.setUint16(54, 5, true); // RATIONAL
  view.setUint32(56, 3, true);
  view.setUint32(60, 76, true); // rational offset relative to exifOffset = 76 (offset 88)

  // Entry 3: tag 3 (lonRef = 'E')
  view.setUint16(64, 3, true);
  view.setUint16(66, 2, true);
  view.setUint32(68, 2, true);
  buf[72] = 0x45; buf[73] = 0x00; // 'E\0'

  // Entry 4: tag 4 (lon = 77 deg, 12 min, 30 sec)
  view.setUint16(76, 4, true);
  view.setUint16(78, 5, true);
  view.setUint32(80, 3, true);
  view.setUint32(84, 100, true); // rational offset relative to exifOffset = 100 (offset 112)

  // Rationals for latitude at offset 88:
  // 28/1, 36/1, 50/1
  view.setUint32(88, 28, true); view.setUint32(92, 1, true);
  view.setUint32(96, 36, true); view.setUint32(100, 1, true);
  view.setUint32(104, 50, true); view.setUint32(108, 1, true);

  // Rationals for longitude at offset 112:
  // 77/1, 12/1, 30/1
  view.setUint32(112, 77, true); view.setUint32(116, 1, true);
  view.setUint32(120, 12, true); view.setUint32(124, 1, true);
  view.setUint32(128, 30, true); view.setUint32(132, 1, true);

  const result = extractExifGpsFromBuffer(buf.buffer);
  assert.notEqual(result, null);
  assert.equal(result?.latitude, 28.6138889);
  assert.equal(result?.longitude, 77.2083333);
});
