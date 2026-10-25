import { useEffect, useMemo, useState } from 'react';
import { CircleMarker, Popup, Tooltip } from 'react-leaflet';

type MappedObservation = {
  id: number;
  damage_class: string;
  confidence: number;
  latitude: number | string;
  longitude: number | string;
  coordinate_source?: string;
  observation_source?: string;
  gps_accuracy_m?: number | null;
  status: string;
  observed_at: string;
};

type NormalizedObservation = Omit<MappedObservation, 'latitude' | 'longitude'> & {
  latitude: number;
  longitude: number;
};

type LocationGroup = {
  key: string;
  latitude: number;
  longitude: number;
  items: NormalizedObservation[];
};

const TOKEN_KEY = 'routiq_access_token';

const colors: Record<string, string> = {
  pothole: '#dc2626',
  longitudinal_crack: '#ea580c',
  transverse_crack: '#ca8a04',
  alligator_crack: '#7c3aed',
};

function readable(value: string): string {
  return String(value || 'unknown')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function groupByLocation(observations: MappedObservation[]): LocationGroup[] {
  const groups = new Map<string, LocationGroup>();

  for (const item of observations) {
    const latitude = Number(item.latitude);
    const longitude = Number(item.longitude);

    if (
      !Number.isFinite(latitude) ||
      !Number.isFinite(longitude) ||
      latitude < -90 ||
      latitude > 90 ||
      longitude < -180 ||
      longitude > 180 ||
      (latitude === 0 && longitude === 0)
    ) {
      continue;
    }

    // Group only virtually identical GPS points, not nearby road locations.
    const key = `${latitude.toFixed(5)},${longitude.toFixed(5)}`;
    const normalized: NormalizedObservation = {
      ...item,
      latitude,
      longitude,
      confidence: Number(item.confidence) || 0,
    };
    const current = groups.get(key);

    if (current) {
      current.items.push(normalized);
    } else {
      groups.set(key, {
        key,
        latitude,
        longitude,
        items: [normalized],
      });
    }
  }

  return [...groups.values()].map((group) => ({
    ...group,
    items: [...group.items].sort(
      (a, b) => new Date(b.observed_at).getTime() - new Date(a.observed_at).getTime()
    ),
  }));
}

export default function RoadDamageMarkers({ refresh = 0 }: { refresh?: number }) {
  const [observations, setObservations] = useState<MappedObservation[]>([]);

  useEffect(() => {
    let active = true;
    const token = localStorage.getItem(TOKEN_KEY);

    if (!token) {
      setObservations([]);
      return () => { active = false; };
    }

    fetch('/api/v1/road-observations/map/', {
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
      .then(async (response) => {
        const text = await response.text();
        let payload: unknown;
        try { payload = text ? JSON.parse(text) : []; } catch { payload = []; }

        if (!response.ok) {
          throw new Error(`Map observations request failed (${response.status}).`);
        }
        return payload;
      })
      .then((payload) => {
        if (active) {
          setObservations(Array.isArray(payload) ? payload as MappedObservation[] : []);
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setObservations([]);
          console.warn(
            'RoutIQ damage overlay unavailable:',
            error instanceof Error ? error.message : error
          );
        }
      });

    return () => { active = false; };
  }, [refresh]);

  const groups = useMemo(() => groupByLocation(observations), [observations]);

  return (
    <>
      {groups.map((group) => {
        const primary = group.items.reduce((best, item) =>
          item.confidence > best.confidence ? item : best
        );
        const color = colors[primary.damage_class] || '#2563eb';
        const count = group.items.length;

        return (
          <CircleMarker
            key={group.key}
            center={[group.latitude, group.longitude]}
            radius={count > 1 ? Math.min(14, 7 + count) : 7}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.9, weight: 2 }}
          >
            {count > 1 && (
              <Tooltip
                permanent
                direction="center"
                opacity={0.95}
                className="routiq-map-cluster-count"
              >
                {count}
              </Tooltip>
            )}
            <Popup>
              <div className="routiq-map-observation-popup">
                <strong>{count} saved observation{count === 1 ? '' : 's'} at this location</strong>
                {count > 1 && (
                  <p className="routiq-map-cluster-note">
                    Near-identical GPS points are grouped. Select an observation below to review its details.
                  </p>
                )}
                {group.items.map((item) => (
                  <div className="routiq-map-observation-item" key={item.id}>
                    <strong>Observation #{item.id} · {readable(item.damage_class)}</strong>
                    <br />
                    Confidence: {(item.confidence * 100).toFixed(1)}%
                    <br />
                    Review status: {readable(item.status)}
                    <br />
                    Coordinates: {item.latitude.toFixed(5)}, {item.longitude.toFixed(5)}
                    <br />
                    Coordinate source: {readable(item.coordinate_source || 'unspecified')}
                    <br />
                    Observation source: {readable(item.observation_source || 'unknown')}
                    <br />
                    {item.gps_accuracy_m != null && (
                      <>GPS accuracy: {Number(item.gps_accuracy_m).toFixed(1)} m<br /></>
                    )}
                    Observed: {new Date(item.observed_at).toLocaleString()}
                  </div>
                ))}
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </>
  );
}
