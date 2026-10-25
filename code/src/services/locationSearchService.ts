import type { SearchResult, Location } from '../types';
import { NOMINATIM_BASE_URL } from '../constants';

type NominatimRecord = {
  place_id?: string | number;
  display_name?: string;
  lat?: string | number;
  lon?: string | number;
  boundingbox?: string[];
  importance?: number;
  address?: {
    country_code?: string;
    country?: string;
  };
};

type PhotonFeature = {
  geometry?: { coordinates?: number[] };
  properties?: Record<string, unknown>;
};

type PhotonResponse = {
  features?: PhotonFeature[];
};

function normalizedText(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

function validCoordinates(lat: number, lon: number): boolean {
  return Number.isFinite(lat) &&
    Number.isFinite(lon) &&
    lat >= -90 && lat <= 90 &&
    lon >= -180 && lon <= 180 &&
    !(lat === 0 && lon === 0);
}

function distanceMeters(a: SearchResult, b: SearchResult): number {
  const lat1 = Number(a.lat) * Math.PI / 180;
  const lat2 = Number(b.lat) * Math.PI / 180;
  const deltaLat = lat2 - lat1;
  const deltaLon = (Number(b.lon) - Number(a.lon)) * Math.PI / 180;
  const haversine = Math.sin(deltaLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;

  return 6371000 * 2 * Math.asin(Math.min(1, Math.sqrt(haversine)));
}

function relevanceScore(query: string, result: SearchResult): number {
  const queryText = normalizedText(query);
  const resultText = normalizedText(result.display_name);
  const tokens = queryText
    .split(' ')
    .filter((token) => token.length >= 3 && !['the', 'and', 'for', 'near'].includes(token));

  if (!tokens.length) return 0;

  const matches = tokens.filter((token) => resultText.includes(token)).length;
  let score = (matches / tokens.length) * 100;

  if (resultText.includes(queryText)) score += 25;

  const firstToken = tokens[0];
  if (firstToken && resultText.startsWith(firstToken)) score += 5;

  return score;
}

function similarity(a: string, b: string): number {
  const first = new Set(normalizedText(a).split(' ').filter(Boolean));
  const second = new Set(normalizedText(b).split(' ').filter(Boolean));
  if (!first.size || !second.size) return 0;

  const common = [...first].filter((token) => second.has(token)).length;
  return common / new Set([...first, ...second]).size;
}

function readText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim()
    ? value.trim()
    : undefined;
}

export class LocationSearchService {
  private static instance: LocationSearchService;
  private static lastNominatimRequestAt = 0;

  static getInstance(): LocationSearchService {
    if (!LocationSearchService.instance) {
      LocationSearchService.instance = new LocationSearchService();
    }
    return LocationSearchService.instance;
  }

  private async searchNominatim(
    query: string,
    limit: number
  ): Promise<SearchResult[]> {
    // Respect the public Nominatim service's one-request-per-second usage limit.
    const delay = Math.max(
      0,
      1000 - (Date.now() - LocationSearchService.lastNominatimRequestAt)
    );

    if (delay > 0) {
      await new Promise((resolve) => setTimeout(resolve, delay));
    }

    LocationSearchService.lastNominatimRequestAt = Date.now();

    const params = new URLSearchParams({
      q: query,
      format: 'jsonv2',
      limit: String(limit),
      addressdetails: '1',
      countrycodes: 'in'
    });

    const response = await fetch(`${NOMINATIM_BASE_URL}?${params}`, {
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(10000)
    });

    if (!response.ok) {
      throw new Error(`Nominatim returned HTTP ${response.status}`);
    }

    const records = await response.json() as NominatimRecord[];

    return records.flatMap((record): SearchResult[] => {
      const lat = Number(record.lat);
      const lon = Number(record.lon);
      const name = readText(record.display_name);

      if (!name || !validCoordinates(lat, lon)) return [];

      const countryCode = record.address?.country_code?.toLowerCase();
      if (countryCode && countryCode !== 'in') return [];

      return [{
        place_id: `nominatim-${String(record.place_id ?? `${lat},${lon}`)}`,
        display_name: name,
        lat: String(lat),
        lon: String(lon),
        boundingbox: record.boundingbox ?? [],
        source: 'OpenStreetMap / Nominatim'
      }];
    });
  }

  private async searchPhoton(
    query: string,
    limit: number
  ): Promise<SearchResult[]> {
    // Add India to help bias ambiguous names toward Indian locations.
    const photonQuery = /\bindia\b/i.test(query)
      ? query
      : `${query}, India`;

    const params = new URLSearchParams({
      q: photonQuery,
      limit: String(limit),
      lang: 'en'
    });

    const response = await fetch(`https://photon.komoot.io/api/?${params}`, {
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(10000)
    });

    if (!response.ok) {
      throw new Error(`Photon returned HTTP ${response.status}`);
    }

    const data = await response.json() as PhotonResponse;
    const features = Array.isArray(data.features) ? data.features : [];

    return features.flatMap((feature): SearchResult[] => {
      const coordinates = feature.geometry?.coordinates;
      if (!coordinates || coordinates.length < 2) return [];

      const lon = Number(coordinates[0]);
      const lat = Number(coordinates[1]);
      if (!validCoordinates(lat, lon)) return [];

      const p = feature.properties ?? {};
      const country = readText(p.country);

      if (country && !/\bindia\b/i.test(country) && country.toLowerCase() !== 'in') {
        return [];
      }

      const streetLine = [
        readText(p.housenumber),
        readText(p.street)
      ].filter(Boolean).join(' ');

      const locality =
        readText(p.city) ??
        readText(p.locality) ??
        readText(p.district) ??
        readText(p.county);

      const displayName = [...new Set([
        readText(p.name),
        streetLine || undefined,
        readText(p.suburb),
        locality,
        readText(p.state),
        country ?? 'India'
      ].filter((part): part is string => Boolean(part)))].join(', ');

      if (!displayName) return [];

      return [{
        place_id: `photon-${String(p.osm_type ?? 'place')}-${String(p.osm_id ?? `${lat},${lon}`)}`,
        display_name: displayName,
        lat: String(lat),
        lon: String(lon),
        boundingbox: [],
        source: 'Photon'
      }];
    });
  }

  async searchLocations(
    query: string,
    limit: number = 5,
    currentLocation?: Location
  ): Promise<SearchResult[]> {
    const cleaned = query.trim().replace(/\s+/g, ' ');
    if (cleaned.length < 3) return [];

    const count = Math.min(10, Math.max(5, limit * 2));

    const [nominatimResult, photonResult] = await Promise.allSettled([
      this.searchNominatim(cleaned, count),
      this.searchPhoton(cleaned, count)
    ]);

    const candidates: SearchResult[] = [];

    if (nominatimResult.status === 'fulfilled') {
      candidates.push(...nominatimResult.value);
    } else {
      console.warn('Nominatim search unavailable.', nominatimResult.reason);
    }

    if (photonResult.status === 'fulfilled') {
      candidates.push(...photonResult.value);
    } else {
      console.warn('Photon search unavailable.', photonResult.reason);
    }

    // De-duplicate only when both name and coordinates closely agree.
    // Same-named results far apart remain separate so the user can choose.
    const scored = candidates
      .map((result) => {
        const score = relevanceScore(cleaned, result);
        let proximityBonus = 0;

        if (
          currentLocation &&
          Number.isFinite(currentLocation.lat) &&
          Number.isFinite(currentLocation.lng)
        ) {
          const lat1 = currentLocation.lat * Math.PI / 180;
          const lat2 = Number(result.lat) * Math.PI / 180;
          const deltaLat = lat2 - lat1;
          const deltaLon = (Number(result.lon) - currentLocation.lng) * Math.PI / 180;

          const h = Math.sin(deltaLat / 2) ** 2 +
            Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;

          const distanceKm = 6371 * 2 *
            Math.asin(Math.min(1, Math.sqrt(h)));

          // Prefer nearby matches modestly; textual relevance remains mandatory.
          proximityBonus = Math.max(0, 12 - distanceKm / 10);
        }

        return { result, score, rank: score + proximityBonus };
      })
      .filter((item) => item.score >= 45)
      .sort((a, b) => b.rank - a.rank);

    const merged: SearchResult[] = [];

    for (const item of scored) {
      const duplicateIndex = merged.findIndex((existing) =>
        distanceMeters(existing, item.result) <= 300 &&
        similarity(existing.display_name, item.result.display_name) >= 0.55
      );

      if (duplicateIndex < 0) {
        merged.push(item.result);
        continue;
      }

      const existing = merged[duplicateIndex];
      const sources = new Set([
        ...(existing.source ?? '').split(' + '),
        ...(item.result.source ?? '').split(' + ')
      ].filter(Boolean));

      existing.source = [...sources].join(' + ');
    }

    return merged.slice(0, Math.max(1, limit));
  }

  convertSearchResultToLocation(result: SearchResult): Location {
    const lat = Number(result.lat);
    const lng = Number(result.lon);

    if (!validCoordinates(lat, lng)) {
      throw new Error('The selected location has invalid coordinates.');
    }

    return {
      lat,
      lng,
      name: result.display_name
    };
  }
}