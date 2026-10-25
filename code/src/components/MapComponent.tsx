import React, { useRef, useEffect } from 'react';
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet';
import { Map as LeafletMap } from 'leaflet';
import type { LatLngTuple } from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { Location, PotholeStatus, PotholeSeverity } from '../types';
import { MAP_CONFIG, TILE_LAYERS, TILE_MAX_NATIVE_ZOOM } from '../constants';
import { PotholeMarkers } from './PotholeMarkers';
import RoadDamageMarkers from './RoadDamageMarkers';
import { RoadHealthOverlay } from './RoadHealthOverlay';

// Fix for default markers in React-Leaflet
import L from 'leaflet';
Reflect.deleteProperty(L.Icon.Default.prototype, '_getIconUrl');
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

interface MapComponentProps {
  location: Location;
  showSatellite: boolean;
  showMajorRoadsOnly: boolean;
  statusFilter?: PotholeStatus | 'all';
  severityFilter?: PotholeSeverity | 'all';
  dateRange?: { start: Date; end: Date };
  refreshTrigger?: number;
  roadHealthEnabled?: boolean;
  showLocationMarker?: boolean;
}

// Component to handle map updates
const MapController: React.FC<{ location: Location }> = ({ location }) => {
  const map = useMap();
  const lat = Number(location.lat);
  const lng = Number(location.lng);

  useEffect(() => {
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;

    map.stop();
    map.invalidateSize({ pan: false });
    map.flyTo([lat, lng], MAP_CONFIG.defaultZoom, {
      animate: true,
      duration: MAP_CONFIG.animationDuration / 1000
    });
  }, [map, lat, lng]);

  return null;
};

export const MapComponent: React.FC<MapComponentProps> = ({
  location,
  showSatellite,
  showMajorRoadsOnly,
  statusFilter = 'all',
  severityFilter = 'all',
  dateRange,
  refreshTrigger = 0,
  roadHealthEnabled = false,
  showLocationMarker = false
}) => {
  const mapRef = useRef<LeafletMap>(null);

  // Determine which tile layer to use
  const getTileUrl = () => {
    if (showSatellite) {
      return TILE_LAYERS.satellite;
    }
    return TILE_LAYERS.standard;
  };

  const getTileAttribution = () => {
    return '&copy; <a href="https://www.esri.com/">Esri</a>';
  };

  const getTileMaxNativeZoom = () => {
    return showSatellite
      ? TILE_MAX_NATIVE_ZOOM.satellite
      : TILE_MAX_NATIVE_ZOOM.standard;
  };

  const center: LatLngTuple = [location.lat, location.lng];

  useEffect(() => {
    // Add scale control when map is ready
    const map = mapRef.current;
    if (map) {
      L.control.scale({
        position: 'bottomleft',
        metric: true,
        imperial: false
      }).addTo(map);
    }
  }, []);

  return (
    <div className="map-container">
      <MapContainer
        center={center}
        zoom={MAP_CONFIG.defaultZoom}
        style={{ height: '100%', width: '100%' }}
        ref={mapRef}
        zoomControl={true}
        scrollWheelZoom={true}
      >
        <TileLayer
          key={showSatellite ? 'satellite' : 'standard'}
          url={getTileUrl()}
          attribution={getTileAttribution()}
          maxZoom={MAP_CONFIG.maxZoom}
          maxNativeZoom={getTileMaxNativeZoom()}
          minZoom={MAP_CONFIG.minZoom}
        />

        {/* Road overlay for major roads only */}
        {showMajorRoadsOnly && !showSatellite && (
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            opacity={0.7}
          />
        )}
        {showLocationMarker && (
          <>
            <CircleMarker
              center={center}
              radius={17}
              pathOptions={{
                color: '#4285F4',
                weight: 1,
                fillColor: '#4285F4',
                fillOpacity: 0.18
              }}
            />
            <CircleMarker
              center={center}
              radius={7}
              pathOptions={{
                color: '#FFFFFF',
                weight: 3,
                fillColor: '#4285F4',
                fillOpacity: 1
              }}
            >
              <Popup>
                <div>
                  <strong>{location.name}</strong>
                  <br />
                  Coordinates: {location.lat.toFixed(5)}, {location.lng.toFixed(5)}
                </div>
              </Popup>
            </CircleMarker>
          </>
        )}

        {/* Pothole markers */}
        <PotholeMarkers
          refresh={refreshTrigger}
          statusFilter={statusFilter}
          severityFilter={severityFilter}
          dateRange={dateRange}
        />

        {/* RoutIQ AI detections saved by the signed-in user */}
        <RoadDamageMarkers refresh={refreshTrigger} />

        {/* Road Health Overlay */}
        {roadHealthEnabled && typeof window !== 'undefined' && Boolean(window.localStorage.getItem('routiq_access_token')) && <RoadHealthOverlay enabled={true} />}

        <MapController location={location} />
      </MapContainer>
    </div>
  );
};
