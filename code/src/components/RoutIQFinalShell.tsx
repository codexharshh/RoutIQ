import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { Location, Pothole, PotholeSeverity, PotholeStatus, PotholeStats, RoadHealthData } from '../types';
import { potholeApiService } from '../services/potholeApiService';
import { roadHealthService } from '../services/roadHealthService';
import { LocationSearch } from './LocationSearch';
import { LocationSearchService } from '../services/locationSearchService';
import { MapComponent } from './MapComponent';
import RoadDamageConsole from './RoadDamageConsole';
import { detectorReadinessMessage } from '../services/detectorReadiness';
import type { DetectorReadiness } from '../services/detectorReadiness';
import ExistingUploadPage from './ExistingUploadPage';
import { getCurrentDeviceLocation, validateCoordinates } from '../services/gpsLocationService';
import './RoutIQFinalShell.css';

type PageKey = 'Dashboard' | 'Map View' | 'Upload & Analyze' | 'Reported Issues' | 'Repair Verification' | 'Analytics' | 'Settings';
type IconName = 'dashboard' | 'map' | 'upload' | 'issues' | 'verify' | 'analytics' | 'settings' | 'search' | 'sun' | 'moon' | 'bell' | 'chevron' | 'arrow' | 'pin' | 'clock' | 'refresh' | 'filter' | 'download' | 'check' | 'alert' | 'road' | 'menu' | 'x' | 'sliders' | 'external' | 'activity' | 'calendar' | 'locate' | 'logout' | 'file' | 'spark' | 'trend' | 'checkCircle';

const NAV_ITEMS: { label: PageKey; icon: IconName; section?: string }[] = [
  { label: 'Dashboard', icon: 'dashboard', section: 'WORKSPACE' },
  { label: 'Map View', icon: 'map' },
  { label: 'Upload & Analyze', icon: 'upload' },
  { label: 'Reported Issues', icon: 'issues', section: 'ROAD INTELLIGENCE' },
  { label: 'Repair Verification', icon: 'verify' },
  { label: 'Analytics', icon: 'analytics', section: 'INSIGHTS' },
  { label: 'Settings', icon: 'settings', section: 'SYSTEM' },
];

type Observation = {
  id: number;
  session?: number | null;
  damage_class: string;
  class_id?: number;
  confidence: number;
  latitude: number | string | null;
  longitude: number | string | null;
  gps_accuracy_m?: number | null;
  assessment_status: string;
  observed_at: string;
  created_at?: string;
  source_name?: string;
  model_name?: string;
  model_version?: string;
  bbox?: number[] | null;
  metadata?: Record<string, unknown> | null;
};

type AISummary = {
  total_observations: number;
  mapped_observations: number;
  sessions: number;
  by_class: Record<string, number>;
  by_status: Record<string, number>;
  last_observed_at: string | null;
};

type TemporalResult = {
  match_id: number;
  observation_a_id: number;
  observation_b_id: number;
  decision: 'same_damage' | 'different_damage' | 'uncertain';
  score: number | null;
  distance_m: number | null;
  temporal_gap_hours: number | null;
  quality_a: { score: number; flags: string[] };
  quality_b: { score: number; flags: string[] };
  reasons: string[];
  abstained: boolean;
  repair_verification?: string;
  image_comparison?: SessionImageComparisonResult;
};

type SessionImageComparisonResult = {
  available: boolean;
  status: 'candidate_visual_similarity' | 'candidate_visual_change' | 'mixed_visual_evidence' | 'insufficient_evidence' | string;
  explanation: string;
  method?: string;
  quality_flags?: string[];
  metrics?: {
    feature_matches?: number;
    homography_inliers?: number;
    alignment_ratio?: number;
    overlap_percent?: number;
    structural_similarity?: number;
    changed_pixel_percent?: number;
    blur_score_a?: number;
    blur_score_b?: number;
    brightness_a?: number;
    brightness_b?: number;
    image_width_a?: number;
    image_height_a?: number;
    image_width_b?: number;
    image_height_b?: number;
  };
};

type SessionEvidenceRecord = {
  id: number;
  title: string;
  source_kind: string;
  status: string;
  created_at: string;
  evidence_available: boolean;
  metadata?: Record<string, unknown> | null;
};

type SessionEvidenceComparisonResponse = {
  comparison_id: number;
  created: boolean;
  session_a_id: number;
  session_b_id: number;
  session_a_title: string;
  session_b_title: string;
  detections_a: number;
  detections_b: number;
  image_comparison: SessionImageComparisonResult;
  repair_verification: 'not_inferred' | string;
};
// RoutIQ same-inspection comparison guard v1
function isSameInspectionPass(a: Observation, b: Observation): boolean {
  const metadataValue = (item: Observation): string => {
    const metadata = item.metadata ?? {};
    const sessionKey =
      metadata.inspection_session_id ??
      metadata.session_id ??
      metadata.upload_id ??
      metadata.batch_id ??
      metadata.inspection_id;

    return sessionKey == null ? '' : String(sessionKey).trim();
  };

  const sessionA = metadataValue(a);
  const sessionB = metadataValue(b);

  if (sessionA && sessionB && sessionA === sessionB) {
    return true;
  }

  const sourceKey = (item: Observation): string =>
    String(item.source_name ?? '')
      .trim()
      .replace(/^.*[\\/]/, '')
      .toLocaleLowerCase();

  const sourceA = sourceKey(a);
  const sourceB = sourceKey(b);

  if (!sourceA || !sourceB || sourceA !== sourceB) {
    return false;
  }

  const timeA = new Date(a.observed_at || a.created_at || '').getTime();
  const timeB = new Date(b.observed_at || b.created_at || '').getTime();

  if (!Number.isFinite(timeA) || !Number.isFinite(timeB)) {
    return false;
  }

  const timeGapMs = Math.abs(timeA - timeB);
  if (timeGapMs > 10 * 60 * 1000) {
    return false;
  }

  const latA = Number(a.latitude);
  const lonA = Number(a.longitude);
  const latB = Number(b.latitude);
  const lonB = Number(b.longitude);

  if (![latA, lonA, latB, lonB].every(Number.isFinite)) {
    return false;
  }

  const radians = (value: number) => value * Math.PI / 180;
  const dLat = radians(latB - latA);
  const dLon = radians(lonB - lonA);
  const rLatA = radians(latA);
  const rLatB = radians(latB);

  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rLatA) * Math.cos(rLatB) * Math.sin(dLon / 2) ** 2;

  const distanceM = 6371000 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));

  return distanceM <= 15;
}

const API_ROOT = '/api/v1';
const ACCESS_KEY = 'routiq_access_token';
const REFRESH_KEY = 'routiq_refresh_token';
const USER_KEY = 'routiq_user';

function tokenValue(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

function readStoredUser(): Record<string, unknown> | null {
  try {
    const value = localStorage.getItem(USER_KEY);
    return value ? JSON.parse(value) as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (typeof payload === 'string' && payload.trim()) return payload;
  if (payload && typeof payload === 'object') {
    const obj = payload as Record<string, unknown>;
    for (const key of ['detail', 'message', 'error']) {
      if (typeof obj[key] === 'string' && (obj[key] as string).trim()) return obj[key] as string;
    }
    if (obj.errors && typeof obj.errors === 'object') {
      const errors = Object.entries(obj.errors as Record<string, unknown>)
        .map(([field, value]) => `${field}: ${Array.isArray(value) ? value.join(', ') : String(value)}`);
      if (errors.length) return errors.join('  |  ');
    }
  }
  return fallback;
}

async function readJsonResponse<T>(response: Response, fallback: string): Promise<T> {
  const raw = await response.text();
  let payload: unknown = null;
  try { payload = raw ? JSON.parse(raw) : null; } catch { payload = raw; }
  if (!response.ok) {
    throw new Error(errorMessage(payload, `${fallback} (HTTP ${response.status}).`));
  }
  return payload as T;
}

async function aiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = tokenValue();
  if (!token) throw new Error('Sign in from Upload & Analyze to access private RoutIQ observations.');
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(`${API_ROOT}${path}`, { ...init, headers });
  if (response.status === 401) {
    throw new Error('Your RoutIQ session has expired. Open Upload & Analyze and sign in again.');
  }
  return readJsonResponse<T>(response, `Request failed at ${path}`);
}

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.75, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true as const };
  const shape: Record<IconName, ReactNode> = {
    dashboard: <><rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/></>,
    map: <><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15M15 6v15"/></>,
    upload: <><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 16v4h16v-4"/></>,
    issues: <><path d="M12 8v5"/><path d="M12 17h.01"/><path d="M10.2 3.8 2.8 17a2 2 0 0 0 1.75 3h14.9a2 2 0 0 0 1.75-3l-7.4-13.2a2.1 2.1 0 0 0-3.6 0z"/></>,
    verify: <><path d="m5 12 4 4L19 6"/><circle cx="12" cy="12" r="9"/></>,
    analytics: <><path d="M4 19V5"/><path d="M4 19h17"/><path d="m7 15 4-4 3 2 5-7"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1 1.4 1.1-1.4 2.4-1.8-.7a8 8 0 0 1-1.9 1.1l-.3 1.9h-2.8l-.3-1.9a8 8 0 0 1-1.9-1.1l-1.8.7-1.4-2.4 1.4-1.1a7 7 0 0 1 0-2.2l-1.4-1.1 1.4-2.4 1.8.7a8 8 0 0 1 1.9-1.1l.3-1.9h2.8l.3 1.9a8 8 0 0 1 1.9 1.1l1.8-.7 1.4 2.4-1.4 1.1a7 7 0 0 1-.1 2.2z" transform="translate(-.7 -1) scale(1.06)"/></>,
    search: <><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/></>,
    sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></>,
    moon: <path d="M20.8 14.1A8.5 8.5 0 0 1 9.9 3.2 8.5 8.5 0 1 0 20.8 14.1z"/>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
    chevron: <path d="m7 10 5 5 5-5"/>,
    arrow: <><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></>,
    pin: <><path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0z"/><circle cx="12" cy="10" r="2.4"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    refresh: <><path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M5.7 9a7 7 0 0 1 11.8-2L20 12M4 12l2.5 5a7 7 0 0 0 11.8-2"/></>,
    filter: <><path d="M4 5h16l-6.5 7.5V19l-3 1v-7.5z"/></>,
    download: <><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 20h16"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    alert: <><path d="M12 8v5"/><path d="M12 17h.01"/><path d="M10.3 3.8 2.9 17a2 2 0 0 0 1.7 3h14.8a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0z"/></>,
    road: <><path d="M6 21 10 3"/><path d="M18 21 14 3"/><path d="M12 6v3m0 3v3m0 3v1"/></>,
    menu: <><path d="M4 6h16M4 12h16M4 18h16"/></>,
    x: <><path d="m6 6 12 12M18 6 6 18"/></>,
    sliders: <><path d="M4 7h9m4 0h3M4 17h3m4 0h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/></>,
    external: <><path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6"/></>,
    activity: <path d="M3 12h4l3-8 4 16 3-8h4"/>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18"/></>,
    locate: <><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/></>,
    logout: <><path d="M10 17l5-5-5-5"/><path d="M15 12H3"/><path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6"/></>,
    file: <><path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10z"/><path d="M13 3v7h7"/></>,
    spark: <><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="m19 16 .8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/></>,
    trend: <><path d="m3 17 6-6 4 3 8-9"/><path d="M15 5h6v6"/></>,
    checkCircle: <><circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/></>,
  };
  return <svg {...common}>{shape[name]}</svg>;
}

function safeCount(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—';
}
function prettyLabel(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}
function displayDate(value?: string | null): string {
  if (!value) return 'Not recorded';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Not recorded' : date.toLocaleString();
}
function localDateInput(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}
function detectorReadinessDescription(readiness: DetectorReadiness | null, error: string, loading: boolean, hasToken: boolean): string {
  if (!hasToken) return 'Sign in to check detector and vision-service readiness.';
  if (loading) return 'Checking detector configuration and vision-service status...';
  if (error) return error;
  if (!readiness) return 'Detector readiness has not been checked.';
  return detectorReadinessMessage(readiness);
}
function downloadFile(filename: string, contents: string, type: string) {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const link = document.createElement('a');
  link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function csvValue(value: unknown): string {
  return `"${String(value ?? '').replace(/"/g, '""')}"`;
}

function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`ri-panel ${className}`}>{children}</section>;
}
function PanelTitle({ icon, title, action }: { icon: IconName; title: string; action?: ReactNode }) {
  return <div className="ri-panel-title"><div className="ri-panel-title-label"><span className="ri-icon-tile"><Icon name={icon} size={17}/></span><h2>{title}</h2></div>{action}</div>;
}
function EmptyState({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return <div className="ri-empty-state"><span className="ri-empty-icon"><Icon name="file" size={22}/></span><strong>{title}</strong><p>{detail}</p>{action}</div>;
}
function InlineError({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return <div className="ri-inline-error" role="alert"><Icon name="alert" size={17}/><span>{text}</span>{onRetry && <button className="ri-link-button" onClick={onRetry}>Retry</button>}</div>;
}

function StatCard({ title, value, subtitle, icon, tone }: { title: string; value: string; subtitle: string; icon: IconName; tone: 'gold' | 'green' | 'red' | 'graphite' }) {
  return <article className="ri-stat-card"><div className={`ri-stat-icon ${tone}`}><Icon name={icon} size={20}/></div><div className="ri-stat-body"><p>{title}</p><strong>{value}</strong><span>{subtitle}</span></div></article>;
}

export default function RoutIQFinalShell() {
  const [activePage, setActivePage] = useState<PageKey>('Dashboard');
  const [pageHistory, setPageHistory] = useState<PageKey[]>([]); // RoutIQ navigation history state v1
  const [uploadSkeletonVisible, setUploadSkeletonVisible] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [darkMode, setDarkMode] = useState(false);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [dateMenuOpen, setDateMenuOpen] = useState(false);
  const [searchText, setSearchText] = useState('');
  // RoutIQ global search live suggestions v1
  const [globalLocationSuggestions, setGlobalLocationSuggestions] = useState<Location[]>([]);
  const [globalSearchLoading, setGlobalSearchLoading] = useState(false);
  const [globalSearchOpen, setGlobalSearchOpen] = useState(false);
  const [currentLocation, setCurrentLocation] = useState<Location>({ lat: 0, lng: 0, name: 'Locating your position...' });
  const [locationReady, setLocationReady] = useState(false);
  const [locationError, setLocationError] = useState('');
  const [locationLoading, setLocationLoading] = useState(false);
  const [showSatellite, setShowSatellite] = useState(false);
  const [showMajorRoadsOnly, setShowMajorRoadsOnly] = useState(false);
  const [roadHealthEnabled, setRoadHealthEnabled] = useState(() => typeof window !== 'undefined' && Boolean(window.localStorage.getItem('routiq_access_token')));
  const [statusFilter, setStatusFilter] = useState<PotholeStatus | 'all'>('all');
  const [severityFilter, setSeverityFilter] = useState<PotholeSeverity | 'all'>('all');
  const [dateRange, setDateRange] = useState<{ start: Date; end: Date } | undefined>();
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [potholes, setPotholes] = useState<Pothole[]>([]);
  const [potholeStats, setPotholeStats] = useState<PotholeStats | null>(null);
  const [roadHealth, setRoadHealth] = useState<RoadHealthData[]>([]);
  const [publicLoading, setPublicLoading] = useState(false);
  const [publicError, setPublicError] = useState('');
  const [observations, setObservations] = useState<Observation[]>([]);
  const [aiSummary, setAiSummary] = useState<AISummary | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState('');
  const [detectorReadiness, setDetectorReadiness] = useState<DetectorReadiness | null>(null);
  const [detectorReadinessLoading, setDetectorReadinessLoading] = useState(false);
  const [detectorReadinessError, setDetectorReadinessError] = useState('');
  const [uploadMode, setUploadMode] = useState<'ai' | 'dashcam'>('ai');
  const [gpsEditor, setGpsEditor] = useState<{ id: number; lat: string; lon: string } | null>(null);
  const [gpsBusy, setGpsBusy] = useState(false);
  const [reviewNotice, setReviewNotice] = useState('');
  const [reviewError, setReviewError] = useState('');
  const [reviewFirst, setReviewFirst] = useState('');
  const [reviewSecond, setReviewSecond] = useState('');
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewResult, setReviewResult] = useState<TemporalResult | null>(null);
  const [dateWindow, setDateWindow] = useState('30');

  const requestCurrentLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setLocationLoading(false);
      setLocationError('Location is not supported by this browser. Open Map View and search for a location.');
      return;
    }

    let finished = false;
    // eslint-disable-next-line prefer-const
    // eslint-disable-next-line prefer-const
    let watchdog: number | undefined;

    const finishRequest = () => {
      if (finished) return false;
      finished = true;
      if (watchdog !== undefined) window.clearTimeout(watchdog);
      return true;
    };

    setLocationLoading(true);
    setLocationError('');

    watchdog = window.setTimeout(() => {
      if (finished) return;
      finished = true;
      setLocationLoading(false);
      setLocationError(
        'Location request timed out. Allow location access for this site and enable Windows Location Services, then retry.'
      );
    }, 20000);

    try {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          if (!finishRequest()) return;

          const lat = position.coords.latitude;
          const lng = position.coords.longitude;

          if (
            !Number.isFinite(lat) ||
            !Number.isFinite(lng) ||
            lat < -90 || lat > 90 ||
            lng < -180 || lng > 180
          ) {
            setLocationLoading(false);
            setLocationError('The browser returned invalid coordinates. Please try again.');
            return;
          }

          setCurrentLocation({
            lat,
            lng,
            name: 'My current location'
          });
          setLocationReady(true);
          setLocationError('');
          setLocationLoading(false);
        },
        (error) => {
          if (!finishRequest()) return;

          setLocationLoading(false);
          const message =
            error.code === error.PERMISSION_DENIED
              ? 'Location access was denied. Allow location permission for localhost in your browser settings, then retry.'
              : error.code === error.POSITION_UNAVAILABLE
                ? 'The device could not determine your location. Enable Windows Location Services or search for a place manually.'
                : 'Location request timed out. Check browser and Windows location settings, then retry.';

          setLocationError(message);
        },
        {
          enableHighAccuracy: true,
          timeout: 18000,
          maximumAge: 0
        }
      );
    } catch {
      if (finishRequest()) {
        setLocationLoading(false);
        setLocationError('The browser could not start location detection. Check site permissions and retry.');
      }
    }
  }, []);
  const hasToken = Boolean(tokenValue());

// RoutIQ global auth gate v1
  const [, setAuthGatePulse] = useState(0);

  useEffect(() => {
    if (hasToken) return;

    const timer = window.setInterval(() => {
      // The existing account form writes the token after successful sign-in.
      // Refresh the parent shell when that token becomes available.
      if (tokenValue()) {
        setAuthGatePulse((value) => value + 1);
      }
    }, 350);

    return () => window.clearInterval(timer);
  }, [hasToken]);

  // RoutIQ YouTube-style upload skeleton v1
  useEffect(() => {
    if (!uploadSkeletonVisible) return;

    const timer = window.setTimeout(
      () => setUploadSkeletonVisible(false),
      650
    );

    return () => window.clearTimeout(timer);
  }, [uploadSkeletonVisible]);
  const storedUser = readStoredUser();
  const userLabel = String(storedUser?.username ?? storedUser?.full_name ?? storedUser?.email ?? 'RoutIQ workspace');
  const userInitials = userLabel.split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((part) => part[0].toUpperCase()).join('') || 'R';

  const refreshPublicData = useCallback(async () => {
    setPublicLoading(true);
    setPublicError('');
    const [statsResult, potholesResult, healthResult] = await Promise.allSettled([
      potholeApiService.getPotholeStats(),
      potholeApiService.getPotholes(),
      roadHealthService.getRoadHealthData(),
    ]);
    const errors: string[] = [];
    if (statsResult.status === 'fulfilled') setPotholeStats(statsResult.value);
    else errors.push(`Pothole statistics: ${statsResult.reason instanceof Error ? statsResult.reason.message : 'request failed'}`);
    if (potholesResult.status === 'fulfilled') setPotholes(potholesResult.value);
    else errors.push(`Road reports: ${potholesResult.reason instanceof Error ? potholesResult.reason.message : 'request failed'}`);
    if (healthResult.status === 'fulfilled') setRoadHealth(healthResult.value);
    else errors.push(`Road Health: ${healthResult.reason instanceof Error ? healthResult.reason.message : 'request failed'}`);
    if (errors.length) setPublicError(errors.join('  |  '));
    setPublicLoading(false);
  }, []);

  const refreshAIData = useCallback(async () => {
    if (!tokenValue()) {
      setObservations([]);
      setAiSummary(null);
      setAiError('');
      setAiLoading(false);
      return;
    }
    setAiLoading(true);
    setAiError('');
    const [observationsResult, summaryResult] = await Promise.allSettled([
      aiFetch<Observation[] | { results?: Observation[] }>('/road-observations/'),
      aiFetch<AISummary>('/road-observations/stats/'),
    ]);
    const errors: string[] = [];
    if (observationsResult.status === 'fulfilled') {
      const data = observationsResult.value;
      setObservations(Array.isArray(data) ? data : Array.isArray(data?.results) ? data.results : []);
    } else errors.push(observationsResult.reason instanceof Error ? observationsResult.reason.message : 'Could not load observations');
    if (summaryResult.status === 'fulfilled') setAiSummary(summaryResult.value);
    else errors.push(summaryResult.reason instanceof Error ? summaryResult.reason.message : 'Could not load AI statistics');
    setAiError(errors.join('  |  '));
    setAiLoading(false);
  }, []);

  const refreshDetectorReadiness = useCallback(async () => {
    if (!tokenValue()) {
      setDetectorReadiness(null);
      setDetectorReadinessError('');
      setDetectorReadinessLoading(false);
      return;
    }
    setDetectorReadinessLoading(true);
    try {
      const report = await aiFetch<DetectorReadiness>('/road-observations/detector-status/');
      if (typeof report.status !== 'string' || typeof report.labels !== 'string' || typeof report.inference_tested !== 'boolean') {
        throw new Error('The detector readiness report is invalid.');
      }
      setDetectorReadiness(report);
      setDetectorReadinessError('');
    } catch (error) {
      setDetectorReadiness(null);
      setDetectorReadinessError(error instanceof Error ? error.message : 'Detector readiness is unavailable.');
    } finally {
      setDetectorReadinessLoading(false);
    }
  }, []);

  useEffect(() => {
    requestCurrentLocation();
  }, [requestCurrentLocation]);
  useEffect(() => {
    const query = searchText.trim();
    let cancelled = false;

    if (query.length < 2) {
      setGlobalLocationSuggestions([]);
      setGlobalSearchLoading(false);
      return;
    }

    setGlobalSearchLoading(true);

    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const service = LocationSearchService.getInstance();
          const results = await service.searchLocations(query, 8, currentLocation);

          if (cancelled) return;

          const places = results
            .map((result) => service.convertSearchResultToLocation(result))
            .filter((place) =>
              place.name.trim().length > 0 &&
              Number.isFinite(place.lat) &&
              Number.isFinite(place.lng) &&
              place.lat >= -90 && place.lat <= 90 &&
              place.lng >= -180 && place.lng <= 180
            );

          setGlobalLocationSuggestions(places);
        } catch (error) {
          if (!cancelled) {
            console.error('Global location search failed.', error);
            setGlobalLocationSuggestions([]);
          }
        } finally {
          if (!cancelled) setGlobalSearchLoading(false);
        }
      })();
    }, 350);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [searchText, currentLocation.lat, currentLocation.lng]);
  useEffect(() => { void refreshPublicData(); }, [refreshPublicData]);
  /* RoutIQ dashboard road-health visibility sync v1 */
  useEffect(() => {
    setRoadHealthEnabled(hasToken);
  }, [hasToken]);

  useEffect(() => {
    if (activePage === 'Dashboard' || activePage === 'Repair Verification' || activePage === 'Analytics' || activePage === 'Settings' || activePage === 'Map View') {
      void refreshAIData();
    }
  }, [activePage, refreshAIData]);
  useEffect(() => {
    if (activePage === 'Settings') void refreshDetectorReadiness();
  }, [activePage, hasToken, refreshDetectorReadiness]);

  useEffect(() => {
    const handleFocus = () => {
      if (activePage !== 'Upload & Analyze') {
        void refreshPublicData();
        void refreshAIData();
      }
    };
    window.addEventListener('focus', handleFocus);
    return () => window.removeEventListener('focus', handleFocus);
  }, [activePage, refreshPublicData, refreshAIData]);

  const sortedObservations = useMemo(() => [...observations].sort((a, b) => {
    const first = new Date(a.observed_at || a.created_at || 0).getTime();
    const second = new Date(b.observed_at || b.created_at || 0).getTime();
    return second - first;
  }), [observations]);

  const mappedObservations = useMemo(() => sortedObservations.filter((item) => item.latitude !== null && item.latitude !== undefined && item.longitude !== null && item.longitude !== undefined), [sortedObservations]);
  // RoutIQ distinct repeat-pass selection v2
  useEffect(() => {
    const validPairs: Array<{ first: Observation; second: Observation }> = [];

    for (let i = 0; i < mappedObservations.length; i += 1) {
      for (let j = i + 1; j < mappedObservations.length; j += 1) {
        const first = mappedObservations[i];
        const second = mappedObservations[j];

        if (!isSameInspectionPass(first, second)) {
          validPairs.push({ first, second });
        }
      }
    }

    if (validPairs.length === 0) {
      const fallbackFirst = mappedObservations[0]
        ? String(mappedObservations[0].id)
        : '';

      if (reviewFirst !== fallbackFirst) setReviewFirst(fallbackFirst);
      if (reviewSecond !== '') setReviewSecond('');
      return;
    }

    const pair =
      validPairs.find(
        (candidate) =>
          String(candidate.first.id) === reviewFirst &&
          String(candidate.second.id) === reviewSecond
      ) ?? validPairs[0];

    const firstId = String(pair.first.id);
    const secondId = String(pair.second.id);

    if (reviewFirst !== firstId) setReviewFirst(firstId);
    if (reviewSecond !== secondId) setReviewSecond(secondId);
  }, [mappedObservations, reviewFirst, reviewSecond]);

  const visibleIssues = useMemo(() => potholes.filter((issue) => {
    const needle = searchText.trim().toLowerCase();
    const searchMatch = !needle || [issue.location_string, issue.description, issue.status, issue.severity, String(issue.id)].some((value) => String(value ?? '').toLowerCase().includes(needle));
    const statusMatch = statusFilter === 'all' || issue.status === statusFilter;
    const severityMatch = severityFilter === 'all' || issue.severity === severityFilter;
    return searchMatch && statusMatch && severityMatch;
  }), [potholes, searchText, statusFilter, severityFilter]);

  const classEntries = useMemo(() => {
    const source = aiSummary?.by_class;
    if (!source) return [];
    return Object.entries(source).filter(([, count]) => Number(count) > 0).sort((a, b) => b[1] - a[1]);
  }, [aiSummary]);
  const maxClassValue = Math.max(1, ...classEntries.map(([, count]) => Number(count)));
  const statusEntries = useMemo(() => {
    const source = aiSummary?.by_status;
    if (!source) return [];
    return Object.entries(source).filter(([, count]) => Number(count) > 0).sort((a, b) => b[1] - a[1]);
  }, [aiSummary]);

  const trendPoints = useMemo(() => {
    const months: { key: string; label: string; value: number }[] = [];
    for (let offset = 5; offset >= 0; offset -= 1) {
      const date = new Date();
      date.setDate(1);
      date.setMonth(date.getMonth() - offset);
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
      months.push({ key, label: date.toLocaleDateString(undefined, { month: 'short' }), value: 0 });
    }
    for (const observation of sortedObservations) {
      const stamp = new Date(observation.observed_at || observation.created_at || 0);
      if (Number.isNaN(stamp.getTime())) continue;
      const key = `${stamp.getFullYear()}-${String(stamp.getMonth() + 1).padStart(2, '0')}`;
      const target = months.find((month) => month.key === key);
      if (target) target.value += 1;
    }
    const allowed = Number(dateWindow);
    if (allowed > 0) {
      const cutoff = new Date(Date.now() - allowed * 24 * 60 * 60 * 1000);
      // Recent activity is presented in the same temporal filter as the dashboard only when requested.
      return months.map((month) => ({ ...month, value: sortedObservations.filter((item) => {
        const date = new Date(item.observed_at || item.created_at || 0);
        return !Number.isNaN(date.getTime()) && date >= cutoff && `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}` === month.key;
      }).length }));
    }
    return months;
  }, [sortedObservations, dateWindow]);

  const handlePage = (page: PageKey) => {
    // RoutIQ navigation history push v1
    if (page !== activePage) {
      setPageHistory((history) => [...history.slice(-29), activePage]);
    }

    // Keep the map clear while the road-health service is unavailable.
    if (page === 'Map View') {
      setRoadHealthEnabled(false);
    }
    setUploadSkeletonVisible(page === 'Upload & Analyze');
    setActivePage(page);
    setMobileNav(false);
    if (page !== 'Repair Verification') {
      setReviewError('');
      setReviewNotice('');
    }
  };

  const handleBack = () => {
    if (pageHistory.length > 0) {
      const previousPage = pageHistory[pageHistory.length - 1];
      setPageHistory(pageHistory.slice(0, -1));
      setActivePage(previousPage);
      setMobileNav(false);
      setRoadHealthEnabled(false);

      if (previousPage !== 'Repair Verification') {
        setReviewError('');
        setReviewNotice('');
      }
      return;
    }

    if (activePage !== 'Dashboard') {
      setActivePage('Dashboard');
      setMobileNav(false);
      setRoadHealthEnabled(false);
    }
  };
const signOut = () => {
    localStorage.removeItem(ACCESS_KEY);
    setRoadHealthEnabled(false);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
    setObservations([]);
    setAiSummary(null);
    setAiError('');
    setActivePage('Upload & Analyze');
  };

  const saveGps = async () => {
    if (!gpsEditor) return;
    const validation = validateCoordinates(gpsEditor.lat, gpsEditor.lon);
    if (!validation.valid || validation.latitude === undefined || validation.longitude === undefined) {
      setReviewError(validation.error || 'Enter valid latitude (-90 to 90) and longitude (-180 to 180).');
      setReviewNotice('');
      return;
    }
    const latitude = validation.latitude;
    const longitude = validation.longitude;
    setGpsBusy(true); setReviewError(''); setReviewNotice('');
    try {
      await aiFetch(`/road-observations/${gpsEditor.id}/location/`, {
        method: 'PATCH',
        body: JSON.stringify({ latitude, longitude }),
      });
      const savedId = gpsEditor.id;
      setGpsEditor(null);
      setReviewNotice(`GPS coordinates saved for observation #${savedId}. Only the coordinates entered here are saved; verify they represent the photo capture location.`);
      setRefreshTrigger((value) => value + 1);
      await refreshAIData();
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : 'Could not save the observation location.');
    } finally {
      setGpsBusy(false);
    }
  };

  const fillGpsEditorWithCurrentLocation = async (id: number) => {
    setGpsBusy(true);
    setReviewError('');
    try {
      const loc = await getCurrentDeviceLocation();
      setGpsEditor({ id, lat: loc.latitude.toFixed(7), lon: loc.longitude.toFixed(7) });
      setReviewNotice(`Current device location acquired: ${loc.latitude.toFixed(6)}, ${loc.longitude.toFixed(6)} (accuracy: Â±${loc.accuracy} m). Verify this represents the damage location before saving.`);
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : 'Unable to acquire current location.');
    } finally {
      setGpsBusy(false);
    }
  };

  const flagForReview = async (id: number) => {
    setReviewError(''); setReviewNotice('');
    try {
      const response = await aiFetch<{ id: number }>(`/road-observations/${id}/assess/`, {
        method: 'POST',
        body: JSON.stringify({ status: 'uncertain', confidence: 0.5, rationale: 'Flagged for manual review; this is not a repair verification.' }),
      });
      void response;
      setReviewNotice(`Observation #${id} flagged for manual review.`);
      await refreshAIData();
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : 'Could not update review status.');
    }
  };



  const compareEvidence = async () => {
    const first = Number(reviewFirst);
    const second = Number(reviewSecond);
    const firstObservation = mappedObservations.find((item) => item.id === first);
    const secondObservation = mappedObservations.find((item) => item.id === second);

    if (
      !first ||
      !second ||
      first === second ||
      !firstObservation ||
      !secondObservation ||
      isSameInspectionPass(firstObservation, secondObservation)
    ) {
      setReviewError(
        'Choose two observations from separate inspection passes. Detections from the same uploaded image cannot be compared.'
      );
      setReviewNotice('');
      return;
    }
    setReviewBusy(true); setReviewError(''); setReviewNotice('Comparing repeated-pass evidence...'); setReviewResult(null);
    try {
      const result = await aiFetch<TemporalResult>('/road-observations/temporal-review/', {
        method: 'POST',
        body: JSON.stringify({ observation_a_id: first, observation_b_id: second, distance_threshold_m: 15 }),
      });
      setReviewResult(result);
      setReviewNotice(`Comparison #${result.match_id} saved. This result is a candidate match, not proof of a repair.`);
      await refreshAIData();
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : 'Temporal review could not be completed.');
      setReviewNotice('');
    } finally {
      setReviewBusy(false);
    }
  };

  const exportObservationsCsv = () => {
    const columns = ['id', 'damage_class', 'confidence', 'latitude', 'longitude', 'assessment_status', 'observed_at', 'source_name', 'model_name', 'model_version'];
    const lines = [columns.map(csvValue).join(','), ...sortedObservations.map((item) => columns.map((column) => csvValue((item as unknown as Record<string, unknown>)[column])).join(','))];
    downloadFile(`routiq-observations-${new Date().toISOString().slice(0, 10)}.csv`, '\uFEFF' + lines.join('\r\n'), 'text/csv;charset=utf-8');
  };
  const exportGeoJson = () => {
    if (!mappedObservations.length) {
      setReviewError('No saved observations contain GPS coordinates. Add a verified photo location first.');
      setReviewNotice('');
      return;
    }
    const payload = {
      type: 'FeatureCollection',
      features: mappedObservations.map((item) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [Number(item.longitude), Number(item.latitude)] },
        properties: { id: item.id, damage_class: item.damage_class, confidence: item.confidence, status: item.assessment_status, observed_at: item.observed_at, source_name: item.source_name },
      })),
    };
    downloadFile(`routiq-mapped-observations-${new Date().toISOString().slice(0, 10)}.geojson`, JSON.stringify(payload, null, 2), 'application/geo+json;charset=utf-8');
    setReviewError('');
  };

  const pageTitles: Record<PageKey, { eyebrow: string; title: string; description: string }> = {
    'Dashboard': { eyebrow: 'OVERVIEW', title: 'Smarter Roads. Better Decisions.', description: 'AI-powered road infrastructure analytics for safer and smarter cities.' },
    'Map View': { eyebrow: 'GEOINTELLIGENCE', title: 'Road condition map', description: 'Explore existing road reports and GPS-tagged AI observations on the live map.' },
    'Upload & Analyze': { eyebrow: 'INSPECTION WORKSPACE', title: 'Upload & Analyze', description: 'Run YOLO road-damage detection or process existing dashcam and GPS files.' },
    'Reported Issues': { eyebrow: 'ROAD INTELLIGENCE', title: 'Reported issues', description: 'Browse recorded pothole reports and their current status from the RoutIQ database.' },
    'Repair Verification': { eyebrow: 'EVIDENCE REVIEW', title: 'Repair verification', description: 'Compare repeated observations and manage uncertain evidence without assuming a repair.' },
    'Analytics': { eyebrow: 'INSIGHTS', title: 'Road analytics', description: 'Explore counts and patterns from saved observations and legacy road reports.' },
    'Settings': { eyebrow: 'SYSTEM', title: 'Workspace settings', description: 'Review the current local workspace, service routes and session state.' },
  };
  const heading = pageTitles[activePage];

  if (!hasToken) {
    return (
      <div className="routiq-final-root">
        <main className="ri-auth-landing" aria-label="RoutIQ account access">
          {/* RoutIQ final split auth layout v1 */}
          <aside className="ri-auth-brand-rail">
            <div className="ri-auth-brand-lockup">
              <span className="ri-auth-roadmark" aria-hidden="true"><i/><b/></span>
              <span className="ri-auth-wordmark">
                <strong>Rout<span>IQ</span></strong>
                <small>SMARTER ROADS.<br/>BETTER DECISIONS.</small>
              </span>
            </div>

            <div className="ri-auth-rail-divider"/>

            <div className="ri-auth-benefits">
              <article className="ri-auth-benefit">
                <span className="ri-auth-benefit-icon"><Icon name="pin" size={21}/></span>
                <div><strong>Detect road issues</strong><p>AI-powered inspections</p></div>
              </article>
              <article className="ri-auth-benefit">
                <span className="ri-auth-benefit-icon"><Icon name="map" size={21}/></span>
                <div><strong>Map and analyze</strong><p>Visual insights for better planning</p></div>
              </article>
              <article className="ri-auth-benefit">
                <span className="ri-auth-benefit-icon"><Icon name="road" size={21}/></span>
                <div><strong>Enable safer roads</strong><p>Turn evidence into repair priorities</p></div>
              </article>
            </div>

            <div className="ri-auth-landscape" aria-hidden="true">
              <div className="ri-auth-landscape-sun"/>
              <div className="ri-auth-hill ri-auth-hill-one"/>
              <div className="ri-auth-hill ri-auth-hill-two"/>
              <div className="ri-auth-curved-road"/>
              <div className="ri-auth-road-dashes"/>
            </div>
          </aside>

          <section className="ri-auth-form-panel" aria-label="Create account or sign in">
            <div className="ri-auth-form-frame">
              <div className="ri-auth-form-brand">
                <span className="ri-auth-roadmark" aria-hidden="true"><i/><b/></span>
                <span className="ri-auth-wordmark">
                  <strong>Rout<span>IQ</span></strong>
                  <small>SMARTER ROADS. BETTER DECISIONS.</small>
                </span>
              </div>
              {/* RoutIQ auth card brand v2 */}
              <RoadDamageConsole />
            </div>
          </section>

          <aside className="ri-auth-showcase">
            <div className="ri-auth-showcase-heading">
              <span className="ri-auth-eyebrow">ROUTIQ ROAD INTELLIGENCE</span>
              <h1>Intelligent insights<br/>for safer, smarter roads</h1>
              <p>RoutIQ combines AI and real-world observations to detect road damage, visualize critical areas, and support better infrastructure decisions.</p>
            </div>

            <section className="ri-auth-map-preview" aria-label="Illustrative RoutIQ product preview">
              <div className="ri-auth-map-topbar">
                <div className="ri-auth-mini-brand"><span className="ri-auth-mini-mark"/>RoutIQ</div>
                <div className="ri-auth-map-pills" aria-label="Map feature preview">
                  <span className="selected">Map</span><span>Satellite</span><span>Street View</span>
                </div>
              </div>

              <div className="ri-auth-map-surface">
                <svg className="ri-auth-map-art" viewBox="0 0 820 390" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
                  <rect x="0" y="0" width="820" height="390" fill="#eef1e5"/>
                  <path d="M-30 88 C130 70 180 170 310 140 S550 32 850 80" fill="none" stroke="#d1e0db" strokeWidth="28"/>
                  <path d="M-30 88 C130 70 180 170 310 140 S550 32 850 80" fill="none" stroke="#c0d5d0" strokeWidth="2"/>

                  <g fill="none" stroke="#d4d9ca" strokeWidth="2">
                    <path d="M-20 35 L210 390"/>
                    <path d="M55 -20 L275 390"/>
                    <path d="M140 -20 L370 390"/>
                    <path d="M280 -20 L500 390"/>
                    <path d="M400 -20 L610 390"/>
                    <path d="M540 -20 L750 390"/>
                    <path d="M680 -20 L870 335"/>
                    <path d="M-40 135 L850 270"/>
                    <path d="M-50 195 L850 330"/>
                    <path d="M-30 350 L850 90"/>
                    <path d="M-30 300 L850 38"/>
                    <path d="M20 390 L660 -20"/>
                    <path d="M180 410 L820 -5"/>
                  </g>

                  <g fill="none" stroke="#fbfaf2" strokeWidth="25" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M-25 292 C95 252 148 335 270 268 S445 125 558 158 S705 277 850 208"/>
                    <path d="M130 -20 C205 70 245 105 345 139 S515 218 575 410"/>
                  </g>
                  <g fill="none" stroke="#e8c454" strokeWidth="7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M-25 292 C95 252 148 335 270 268 S445 125 558 158 S705 277 850 208"/>
                    <path d="M130 -20 C205 70 245 105 345 139 S515 218 575 410"/>
                  </g>
                  <g fill="none" stroke="#fff4cb" strokeWidth="2.5" strokeLinecap="round">
                    <path d="M-25 292 C95 252 148 335 270 268 S445 125 558 158 S705 277 850 208"/>
                  </g>

                  <g fill="none" stroke="#78a67d" strokeWidth="5" strokeLinecap="round">
                    <path d="M65 48 C145 96 185 125 245 151"/>
                    <path d="M498 202 C548 226 590 252 637 310"/>
                  </g>
                  <path d="M495 61 L640 8" fill="none" stroke="#d76559" strokeWidth="6" strokeLinecap="round"/>
                  <path d="M580 165 L695 108" fill="none" stroke="#d76559" strokeWidth="4" strokeLinecap="round"/>

                  <g fill="#707c67" fontFamily="Arial, sans-serif" fontSize="12" fontWeight="700" letterSpacing="1.6">
                    <text x="285" y="88">MORADABAD</text>
                    <text x="65" y="209">CIVIL LINES</text>
                    <text x="646" y="330">RAMPUR ROAD</text>
                    <text x="320" y="355">ROAD NETWORK</text>
                  </g>
                </svg>

                <div className="ri-auth-map-hero">
                  <span className="ri-auth-map-hero-icon"><Icon name="road" size={20}/></span>
                  <div><strong>Smarter roads.<br/>Better decisions.</strong><small>AI-powered road intelligence</small></div>
                </div>

                <span className="ri-auth-map-label label-one">MORADABAD</span>
                <span className="ri-auth-map-label label-two">CIVIL LINES</span>
                <span className="ri-auth-map-label label-three">RAMPUR ROAD</span>

                <span className="ri-auth-map-marker marker-one red">!</span>
                <span className="ri-auth-map-marker marker-two amber">!</span>
                <span className="ri-auth-map-marker marker-three green">✓</span>
                <span className="ri-auth-map-marker marker-four green">✓</span>
                <span className="ri-auth-map-marker marker-five amber">!</span>

                <div className="ri-auth-map-popup callout-detection">
                  <span className="ri-auth-demo-road-photo"><Icon name="road" size={22}/></span>
                  <div>
                    <span className="ri-auth-demo-tag">AI DETECTION · EXAMPLE</span>
                    <strong>Pothole detected</strong>
                    <small>High severity · Sample preview</small>
                  </div>
                </div>

                <div className="ri-auth-map-popup callout-gps">
                  <span className="ri-auth-demo-road-photo gps"><Icon name="pin" size={22}/></span>
                  <div>
                    <span className="ri-auth-demo-tag green">GPS MAPPING · EXAMPLE</span>
                    <strong>Location recorded</strong>
                    <small>Coordinates linked to evidence</small>
                  </div>
                </div>

                <div className="ri-auth-map-popup callout-repair">
                  <span className="ri-auth-demo-road-photo repair"><Icon name="activity" size={22}/></span>
                  <div>
                    <span className="ri-auth-demo-tag">REPAIR REVIEW · EXAMPLE</span>
                    <strong>Evidence needs review</strong>
                    <small>Human verification before decisions</small>
                  </div>
                </div>

                <span className="ri-auth-map-scale">ILLUSTRATIVE PREVIEW · NOT LIVE DATA</span>
              </div>
            </section>

            <div className="ri-auth-feature-grid">
              <article className="ri-auth-feature-card">
                <span className="ri-auth-feature-icon"><Icon name="activity" size={20}/></span>
                <strong>AI road inspection</strong>
                <p>Detect potholes, cracks and surface damage from images and videos.</p>
              </article>
              <article className="ri-auth-feature-card">
                <span className="ri-auth-feature-icon green"><Icon name="pin" size={20}/></span>
                <strong>GPS-linked evidence</strong>
                <p>Connect saved observations to their recorded locations.</p>
              </article>
              <article className="ri-auth-feature-card">
                <span className="ri-auth-feature-icon"><Icon name="analytics" size={20}/></span>
                <strong>Review before decisions</strong>
                <p>Support human review with traceable evidence.</p>
              </article>
            </div>

            <div className="ri-auth-impact-strip">
              <div><strong>From observations to safer roads</strong><p>Evidence-led monitoring for better infrastructure decisions.</p></div>
              <div className="ri-auth-impact-items">
                <span><i/>Visualize conditions</span>
                <span><i/>Track issue status</span>
                <span><i/>Support repairs</span>
              </div>
            </div>

            <p className="ri-auth-preview-disclaimer">Product illustration only. Map markers and road examples are not live observations.</p>
          </aside>
        </main>
      </div>
    );
  }
  return (
    <div className={`routiq-final-root${darkMode ? ' ri-dark' : ''}`}>
      <aside className={`ri-sidebar${mobileNav ? ' is-open' : ''}`}>
        <button className="ri-mobile-close" onClick={() => setMobileNav(false)} aria-label="Close navigation"><Icon name="x"/></button>
        <div className="ri-brand">
          <span className="ri-brand-symbol"><span/><i/></span>
          <span className="ri-brand-copy"><strong>Rout<span>IQ</span></strong><small>SMARTER ROADS. BETTER DECISIONS.</small></span>
        </div>
        <div className="ri-nav-caption">MAIN MENU</div>
        <nav className="ri-nav" aria-label="Main navigation">
          {NAV_ITEMS.map((item) => <div className="ri-nav-wrap" key={item.label}>
            {item.section && <span className="ri-nav-section">{item.section}</span>}
            <button className={`ri-nav-item${activePage === item.label ? ' active' : ''}`} onClick={() => handlePage(item.label)} aria-current={activePage === item.label ? 'page' : undefined}>
              <Icon name={item.icon} size={18}/><span>{item.label}</span>{item.label === 'Repair Verification' && mappedObservations.length > 0 && <em className="ri-nav-count">{mappedObservations.length}</em>}
            </button>
          </div>)}
        </nav>
        <div className="ri-sidebar-spacer"/>
        <div className="ri-sidebar-promo">
          <div className="ri-promo-art"><span className="ri-promo-road"/><span className="ri-promo-sun"/></div>
          <p>Better infrastructure<br/>for a safer tomorrow.</p>
          <span className="ri-promo-caption">INSPECT  |  UNDERSTAND  |  IMPROVE</span>
        </div>
        <div className="ri-sidebar-bottom"><span className="ri-status-dot"/><span>LOCAL WORKSPACE</span><span className="ri-version">RoutIQ</span></div>
      </aside>

      {mobileNav && <button aria-label="Close navigation backdrop" className="ri-sidebar-backdrop" onClick={() => setMobileNav(false)}/>}

      <div className="ri-app-main">
        <header className="ri-topbar">
          <button className="ri-mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Icon name="menu"/></button>
          <button
            type="button"
            className="ri-back-button"
            onClick={handleBack}
            disabled={pageHistory.length === 0 && activePage === 'Dashboard'}
            aria-label="Go back to previous page"
            title="Go back"
          >←</button>
          <div className="ri-global-search-wrap">
            <div className="ri-global-search">
              <Icon name="search" size={18}/>
              <input
                value={searchText}
                onChange={(event) => {
                  setSearchText(event.target.value);
                  setGlobalSearchOpen(true);
                }}
                onFocus={() => {
                  if (searchText.trim().length >= 2) setGlobalSearchOpen(true);
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    setGlobalSearchOpen(false);
                    handlePage('Reported Issues');
                  }
                  if (event.key === 'Escape') setGlobalSearchOpen(false);
                }}
                placeholder="Search road reports, places, or issue IDs..."
                aria-label="Search road reports, places, or issue IDs"
                aria-expanded={globalSearchOpen}
                aria-controls="ri-global-search-results"
                autoComplete="off"
              />
            {searchText.trim().length > 0 && (
              <button
                type="button"
                className="ri-global-search-clear"
                aria-label="Clear search"
                title="Clear search"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  setSearchText('');
                  setGlobalLocationSuggestions([]);
                  setGlobalSearchOpen(false);
                }}
              >
                <Icon name="x" size={15}/>
              </button>
            )}


            </div>

            {globalSearchOpen && searchText.trim().length >= 2 && (
              <div className="ri-global-search-results" id="ri-global-search-results" role="listbox" aria-label="Search suggestions">
                <div className="ri-global-search-caption">
                  {globalSearchLoading ? 'Searching places...' : 'Matching places'}
                </div>

                {globalLocationSuggestions.map((place, index) => (
                  <button
                    type="button"
                    role="option"
                    aria-selected={false}
                    key={`${place.lat}-${place.lng}-${index}`}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      setCurrentLocation(place);
                      setLocationReady(true);
                      setLocationError('');
                      setGlobalSearchOpen(false);
                      setGlobalLocationSuggestions([]);
                      handlePage('Map View');
                    }}
                  >
                    <Icon name="pin" size={16}/>
                    <span className="ri-global-search-place">
                      <strong>{place.name}</strong>
                      <small>{place.lat.toFixed(5)}, {place.lng.toFixed(5)}</small>
                    </span>
                  </button>
                ))}

                {!globalSearchLoading && globalLocationSuggestions.length === 0 && (
                  <p className="ri-global-search-empty">No matching places found.</p>
                )}

                <button
                  type="button"
                  className="ri-global-search-report-action"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    setGlobalSearchOpen(false);
                    handlePage('Reported Issues');
                  }}
                >
                  Search road reports and issue IDs for "{searchText}"
                </button>
              </div>
            )}
          </div>
          <div className="ri-topbar-actions">
            <div className="ri-theme-switch" aria-label="Theme">
              <button className={!darkMode ? 'selected' : ''} onClick={() => setDarkMode(false)} title="Light mode" aria-label="Light mode"><Icon name="sun" size={16}/></button>
              <button className={darkMode ? 'selected' : ''} onClick={() => setDarkMode(true)} title="Dark mode" aria-label="Dark mode"><Icon name="moon" size={16}/></button>
            </div>
            <button className="ri-icon-button" title="Refresh data" aria-label="Refresh data" onClick={() => { void refreshPublicData(); void refreshAIData(); setRefreshTrigger((value) => value + 1); }}><Icon name="refresh"/></button>
            <div className="ri-profile-wrap">
  <button
    type="button"
    className="ri-profile ri-profile-trigger"
    aria-label="Account menu"
    aria-haspopup="menu"
    aria-expanded={profileMenuOpen}
    onClick={() => { setProfileMenuOpen((open) => !open); setDateMenuOpen(false); }}
  >
    <div className="ri-avatar">{userInitials}</div>
    <div className="ri-profile-copy">
      <strong>{userLabel}</strong>
      <small>{hasToken ? 'Signed in to RoutIQ' : 'Local workspace'}</small>
    </div>
    <Icon name="chevron" size={15}/>
  </button>
  {profileMenuOpen && (
    <div className="ri-profile-menu" role="menu" aria-label="Account options">
      <div className="ri-profile-menu-account">
        <strong>{userLabel}</strong>
        <small>{hasToken ? 'Signed in to RoutIQ' : 'Local workspace'}</small>
      </div>
      {hasToken && (
        <button type="button" role="menuitem" onClick={() => { setProfileMenuOpen(false); signOut(); }}>
          <Icon name="logout" size={15}/>Sign out
        </button>
      )}
    </div>
  )}
</div>
          </div>
        </header>

        <main className="ri-content">
          <div className="ri-page-heading">
            <div><div className="ri-eyebrow">{heading.eyebrow} <span className="ri-eyebrow-line"/></div><h1>{heading.title}</h1><p>{heading.description}</p></div>
            <div className={activePage === 'Settings' ? 'ri-heading-actions ri-heading-actions-hidden' : 'ri-heading-actions'}>
              <div className="ri-date-filter-wrap">
  <button
    type="button"
    className="ri-date-filter"
    aria-label="Observation trend period"
    aria-haspopup="menu"
    aria-expanded={dateMenuOpen}
    onClick={() => { setDateMenuOpen((open) => !open); setProfileMenuOpen(false); }}
  >
    <Icon name="calendar" size={15}/>
    <span>{dateWindow === '7' ? 'Last 7 days' : dateWindow === '30' ? 'Last 30 days' : dateWindow === '90' ? 'Last 90 days' : 'All time'}</span>
    <Icon name="chevron" size={13}/>
  </button>
  {dateMenuOpen && (
    <div className="ri-date-menu" role="menu" aria-label="Observation trend period">
      <button type="button" role="menuitemradio" aria-checked={dateWindow === '7'} className={dateWindow === '7' ? 'selected' : ''} onClick={() => { setDateWindow('7'); setDateMenuOpen(false); }}>Last 7 days</button>
      <button type="button" role="menuitemradio" aria-checked={dateWindow === '30'} className={dateWindow === '30' ? 'selected' : ''} onClick={() => { setDateWindow('30'); setDateMenuOpen(false); }}>Last 30 days</button>
      <button type="button" role="menuitemradio" aria-checked={dateWindow === '90'} className={dateWindow === '90' ? 'selected' : ''} onClick={() => { setDateWindow('90'); setDateMenuOpen(false); }}>Last 90 days</button>
      <button type="button" role="menuitemradio" aria-checked={dateWindow === '0'} className={dateWindow === '0' ? 'selected' : ''} onClick={() => { setDateWindow('0'); setDateMenuOpen(false); }}>All time</button>
    </div>
  )}
</div>

            </div>
          </div>

          {(activePage === 'Dashboard') && (
            <DashboardPage
              hasToken={hasToken}
              aiSummary={aiSummary}
              aiError={aiError}
              aiLoading={aiLoading}
              potholeStats={potholeStats}
              potholes={potholes}
              roadHealth={roadHealth}
              publicLoading={publicLoading}
              publicError={publicError}
              observations={sortedObservations}
              classEntries={classEntries}
              maxClassValue={maxClassValue}
              trendPoints={trendPoints}
              currentLocation={currentLocation}
              locationReady={locationReady}
              locationError={locationError}
              locationLoading={locationLoading}
              onRetryLocation={requestCurrentLocation}
              showSatellite={showSatellite}
              setShowSatellite={setShowSatellite}
              showMajorRoadsOnly={showMajorRoadsOnly}
              statusFilter={statusFilter}
              severityFilter={severityFilter}
              roadHealthEnabled={roadHealthEnabled}
              setRoadHealthEnabled={setRoadHealthEnabled}
              dateRange={dateRange}
              refreshTrigger={refreshTrigger}
              onNavigate={handlePage}
              onRefresh={() => { void refreshPublicData(); void refreshAIData(); setRefreshTrigger((value) => value + 1); }}
            />
          )}

          {activePage === 'Map View' && (
            <MapViewPage
              currentLocation={currentLocation}
              setCurrentLocation={(location) => { setCurrentLocation(location); setLocationReady(true); setLocationError(''); }}
              locationReady={locationReady}
              locationError={locationError}
              locationLoading={locationLoading}
              onRetryLocation={requestCurrentLocation}
              showSatellite={showSatellite}
              setShowSatellite={setShowSatellite}
              showMajorRoadsOnly={showMajorRoadsOnly}
              setShowMajorRoadsOnly={setShowMajorRoadsOnly}
              roadHealthEnabled={roadHealthEnabled}
              setRoadHealthEnabled={setRoadHealthEnabled}
              statusFilter={statusFilter}
              setStatusFilter={setStatusFilter}
              severityFilter={severityFilter}
              setSeverityFilter={setSeverityFilter}
              dateRange={dateRange}
              setDateRange={setDateRange}
              refreshTrigger={refreshTrigger}
              refresh={refreshPublicData}
              error={publicError}
            />
          )}

          {activePage === 'Upload & Analyze' && (
            <div className="ri-upload-workspace">
              <div className="ri-mode-tabs" role="tablist" aria-label="Inspection mode">
                <button className={uploadMode === 'ai' ? 'selected' : ''} onClick={() => setUploadMode('ai')} role="tab" aria-selected={uploadMode === 'ai'}><Icon name="spark" size={16}/>AI Detection Studio</button>
                <button className={uploadMode === 'dashcam' ? 'selected' : ''} onClick={() => setUploadMode('dashcam')} role="tab" aria-selected={uploadMode === 'dashcam'}><Icon name="road" size={16}/>Dashcam & GPS Processing</button>
              </div>
              <div className="ri-embedded-legacy">
                {uploadSkeletonVisible ? (
                  <div className="ri-upload-skeleton" role="status" aria-busy="true" aria-label="Loading inspection workspace">
                    <div className="ri-skeleton-heading">
                      <span className="ri-skeleton-block ri-skeleton-icon"/>
                      <div className="ri-skeleton-title-group">
                        <span className="ri-skeleton-block ri-skeleton-line medium"/>
                        <span className="ri-skeleton-block ri-skeleton-line short"/>
                      </div>
                    </div>
                    <div className="ri-skeleton-grid">
                      <div className="ri-skeleton-card">
                        <span className="ri-skeleton-block ri-skeleton-line medium"/>
                        <span className="ri-skeleton-block ri-skeleton-preview"/>
                        <span className="ri-skeleton-block ri-skeleton-line"/>
                        <span className="ri-skeleton-block ri-skeleton-line short"/>
                      </div>
                      <div className="ri-skeleton-card">
                        <span className="ri-skeleton-block ri-skeleton-line medium"/>
                        <span className="ri-skeleton-block ri-skeleton-input"/>
                        <span className="ri-skeleton-block ri-skeleton-input"/>
                        <span className="ri-skeleton-block ri-skeleton-action"/>
                      </div>
                    </div>
                    <span className="ri-skeleton-block ri-skeleton-strip"/>
                  </div>
                ) : uploadMode === 'ai' ? (
                  <RoadDamageConsole/>
                ) : (
                  <ExistingUploadPage onNavigateToMap={() => handlePage('Map View')}/>
                )}
              </div>
            </div>
          )}

          {activePage === 'Reported Issues' && (
            <ReportedIssuesPage
              observations={sortedObservations}
              aiLoading={aiLoading}
              reviewError={reviewError}
              reviewNotice={reviewNotice}
              refreshAI={() => void refreshAIData()}
              issues={visibleIssues}
              allCount={potholes.length}
              stats={potholeStats}
              loading={publicLoading}
              error={publicError}
              searchText={searchText}
              statusFilter={statusFilter}
              severityFilter={severityFilter}
              setStatusFilter={setStatusFilter}
              setSeverityFilter={setSeverityFilter}
              refresh={() => void refreshPublicData()}
              onOpenMap={(issue) => {
                const lat = Number(issue.latitude), lng = Number(issue.longitude);
                if (Number.isFinite(lat) && Number.isFinite(lng)) setCurrentLocation({ lat, lng, name: issue.location_string || `Issue #${issue.id}` });
                handlePage('Map View');
              }}
            />
          )}

          {activePage === 'Repair Verification' && (
            <RepairVerificationPage
              hasToken={hasToken}
              observations={sortedObservations}
              mappedObservations={mappedObservations}
              aiLoading={aiLoading}
              aiSummary={aiSummary}
              aiError={aiError}
              gpsEditor={gpsEditor}
              setGpsEditor={setGpsEditor}
              gpsBusy={gpsBusy}
              onUseCurrentLocation={fillGpsEditorWithCurrentLocation}
              saveGps={() => void saveGps()}
              reviewNotice={reviewNotice}
              reviewError={reviewError}
              reviewFirst={reviewFirst}
              setReviewFirst={setReviewFirst}
              reviewSecond={reviewSecond}
              setReviewSecond={setReviewSecond}
              reviewBusy={reviewBusy}
              reviewResult={reviewResult}
              compareEvidence={() => void compareEvidence()}
              flagForReview={(id) => void flagForReview(id)}
              refresh={() => void refreshAIData()}
              exportCsv={exportObservationsCsv}
              exportGeoJson={exportGeoJson}
              onSignIn={() => handlePage('Upload & Analyze')}
            />
          )}

          {activePage === 'Analytics' && (
            <AnalyticsPage
              publicLoading={publicLoading}
              dateWindow={dateWindow}
              hasToken={hasToken}
              aiSummary={aiSummary}
              observations={sortedObservations}
              classEntries={classEntries}
              maxClassValue={maxClassValue}
              statusEntries={statusEntries}
              potholeStats={potholeStats}
              roadHealth={roadHealth}
              publicError={publicError}
              aiError={aiError}
              loading={aiLoading || publicLoading}
              onRefresh={() => { void refreshAIData(); void refreshPublicData(); }}
              onUpload={() => handlePage('Upload & Analyze')}
            />
          )}

          {activePage === 'Settings' && (
            <SettingsPage
              hasToken={hasToken}
              userLabel={userLabel}
              aiError={aiError}
              publicError={publicError}
              aiSummary={aiSummary}
              loading={aiLoading || publicLoading}
              detectorReadiness={detectorReadiness}
              detectorReadinessLoading={detectorReadinessLoading}
              detectorReadinessError={detectorReadinessError}
              onRefresh={() => { void refreshAIData(); void refreshPublicData(); void refreshDetectorReadiness(); }}
              onSignOut={signOut}
              onSignIn={() => handlePage('Upload & Analyze')}
            />
          )}

                    </main>
          <footer className="ri-footer"><span>RoutIQ - Smarter roads. Better decisions.</span></footer>
        </div>
      </div>
    );
}

function DashboardPage(props: {
  hasToken: boolean; aiSummary: AISummary | null; aiError: string; aiLoading: boolean;
  potholeStats: PotholeStats | null; potholes: Pothole[]; roadHealth: RoadHealthData[];
  publicLoading: boolean; publicError: string; observations: Observation[];
  classEntries: [string, number][]; maxClassValue: number; trendPoints: { key: string; label: string; value: number }[];
  currentLocation: Location; locationReady: boolean; locationError: string; locationLoading: boolean; onRetryLocation: () => void; showSatellite: boolean; setShowSatellite: (value: boolean) => void; showMajorRoadsOnly: boolean; statusFilter: PotholeStatus | 'all';
  severityFilter: PotholeSeverity | 'all'; roadHealthEnabled: boolean; setRoadHealthEnabled: (value: boolean) => void; dateRange?: { start: Date; end: Date }; refreshTrigger: number;
  onNavigate: (page: PageKey) => void; onRefresh: () => void;
}) {
  const mappedCount = props.aiSummary?.mapped_observations;
  const mappedReportCount = props.potholes.filter((item) =>
    item.latitude != null && item.longitude != null &&
    String(item.latitude).trim() !== '' && String(item.longitude).trim() !== '' &&
    Number.isFinite(Number(item.latitude)) && Number.isFinite(Number(item.longitude)) &&
    Number(item.latitude) >= -90 && Number(item.latitude) <= 90 &&
    Number(item.longitude) >= -180 && Number(item.longitude) <= 180
  ).length;
  const gpsMappedObservationCount = props.observations.filter((item) =>
    item.latitude != null && item.longitude != null &&
    String(item.latitude).trim() !== '' && String(item.longitude).trim() !== '' &&
    Number.isFinite(Number(item.latitude)) && Number.isFinite(Number(item.longitude)) &&
    Number(item.latitude) >= -90 && Number(item.latitude) <= 90 &&
    Number(item.longitude) >= -180 && Number(item.longitude) <= 180
  ).length;
  const uncertainCount = props.aiSummary?.by_status?.uncertain ?? 0;
  const totalPotholes = props.potholeStats?.total_reports;
  const stats = [
    { title: 'AI observations', value: props.hasToken ? (props.aiLoading && !props.aiSummary ? '...' : safeCount(props.aiSummary?.total_observations)) : 'Sign in', subtitle: props.hasToken ? 'Saved in your account' : 'Sign in to view private data', icon: 'alert' as IconName, tone: 'gold' as const },
    { title: 'GPS mapped', value: props.hasToken ? safeCount(mappedCount) : '—', subtitle: props.hasToken ? 'Observations with coordinates' : 'Account access required', icon: 'pin' as IconName, tone: 'green' as const },
    { title: 'Existing reports', value: props.publicLoading && totalPotholes === undefined ? '...' : safeCount(totalPotholes), subtitle: 'Legacy road reports', icon: 'road' as IconName, tone: 'graphite' as const },
    { title: 'Needs review', value: props.hasToken ? safeCount(uncertainCount) : '—', subtitle: 'Marked uncertain for review', icon: 'clock' as IconName, tone: 'red' as const },
  ];
  const roadHealthCounts = props.roadHealth.reduce<Record<string, number>>((counts, item) => {
    counts[item.health_status] = (counts[item.health_status] ?? 0) + 1;
    return counts;
  }, {});
  return <>
    <div className="ri-stats-grid">{stats.map((stat) => <StatCard key={stat.title} {...stat}/>)}</div>
    {props.publicError && <InlineError text={props.publicError} onRetry={props.onRefresh}/>}
    {props.hasToken && props.aiError && <InlineError text={props.aiError} onRetry={props.onRefresh}/>}
    <div className="ri-dashboard-grid">
      <Panel className="ri-map-panel">
        <PanelTitle icon="pin" title="Road Condition Map"/>

        <div className="ri-map-context"><span className="ri-live-dot"/><span>{props.currentLocation.name}</span><span className="ri-context-sep"> | </span><span>Interactive road reports</span></div>
        <div className="ri-dashboard-map-toolbar">
          <div className="ri-dashboard-map-mode" role="group" aria-label="Map style">
            <button
              type="button"
              className={!props.showSatellite ? 'active' : ''}
              aria-pressed={!props.showSatellite}
              onClick={() => props.setShowSatellite(false)}
            >
              <Icon name="map" size={14}/> Map
            </button>
            <button
              type="button"
              className={props.showSatellite ? 'active' : ''}
              aria-pressed={props.showSatellite}
              onClick={() => props.setShowSatellite(true)}
            >
              <Icon name="map" size={14}/> Satellite
            </button>
          </div>
          <button
            type="button"
            className="ri-dashboard-map-action"
            disabled={props.locationLoading}
            onClick={props.onRetryLocation}
          >
            <Icon name="locate" size={14}/>
            {props.locationLoading ? 'Locating...' : 'My current location'}
          </button>
        </div>
        <div className="ri-map-preview">
          {props.locationReady ? <MapComponent
            location={props.currentLocation} showSatellite={props.showSatellite}
            showMajorRoadsOnly={props.showMajorRoadsOnly} statusFilter={props.statusFilter}
            severityFilter={props.severityFilter} dateRange={props.dateRange}
            refreshTrigger={props.refreshTrigger} roadHealthEnabled={false}
           showLocationMarker={true} /> : <div className="ri-empty-compact" role="status">
            <strong>{props.locationLoading ? 'Finding your location...' : 'Map location needed'}</strong>
            <p>{props.locationError || 'Allow location access to center the map on your current position.'}</p>
            <button className="ri-small-button" onClick={props.onRetryLocation}>{props.locationLoading ? 'Requesting location...' : 'Use my current location'}</button>
          </div>}
        </div>
        <div className="ri-map-legend">
          <span><i className="ri-legend-dot legacy"/>Existing reports ({mappedReportCount} GPS mapped)</span>
          <span><i className="ri-legend-dot ai"/>AI observations ({props.hasToken ? `${gpsMappedObservationCount} GPS mapped` : 'sign in required'})</span>
          <span><i className="ri-legend-dot health"/>Road health ({props.roadHealth.length} segments, {props.roadHealthEnabled ? 'on' : 'off'})</span>
        </div>
      </Panel>
      <div className="ri-dashboard-side">
        <Panel>
          <PanelTitle icon="analytics" title="Issue Distribution" action={<span className="ri-subtle-tag">From saved data</span>}/>
          {!props.hasToken ? <EmptyState title="Sign in to view AI distribution" detail="Private observation counts are shown only for the signed-in RoutIQ account." action={<button className="ri-small-button" onClick={() => props.onNavigate('Upload & Analyze')}>Open AI workspace</button>}/> :
            props.aiLoading && !props.aiSummary ? <div className="ri-loading-line">Loading saved observations...</div> :
            props.aiError && !props.aiSummary ? <InlineError text={props.aiError}/> :
            !props.classEntries.length ? <EmptyState title="No AI observations yet" detail="Upload a road image to populate the distribution chart." action={<button className="ri-small-button" onClick={() => props.onNavigate('Upload & Analyze')}>Upload image</button>}/> :
            <div className="ri-distribution">
              <div className="ri-donut-wrap"><div className="ri-donut" style={{ background: donutBackground(props.classEntries) }}><div><strong>{safeCount(props.aiSummary?.total_observations)}</strong><span>Total<br/>observations</span></div></div></div>
              <div className="ri-class-legend">{props.classEntries.map(([key, count], index) => <div className="ri-class-row" key={key}><i className={`ri-class-dot c${index % 5}`}/><span>{prettyLabel(key)}</span><strong>{safeCount(count)}</strong></div>)}</div>
            </div>
          }
        </Panel>

        <Panel>
          <PanelTitle icon="activity" title="Road Health Status"/>
          {props.publicLoading ? <div className="ri-loading-line">Loading road health...</div> : !props.roadHealth.length ? <div className="ri-empty-compact">No road-health segments available in the current database.</div> :
            <div className="ri-health-rows">{[['critical','Critical'],['warning','Warning'],['caution','Caution'],['good','Good']].map(([key,label]) => <div className="ri-health-row" key={key}><span className={`ri-health-dot ${key}`}/><span>{label}</span><strong>{roadHealthCounts[key] ?? 0}</strong></div>)}</div>
          }
        </Panel>
      </div>
    </div>
    <Panel className="ri-recent-panel">
      <PanelTitle icon="file" title="Recent Detections" action={<button className="ri-text-action" onClick={() => props.onNavigate('Repair Verification')}>View observations <Icon name="arrow" size={14}/></button>}/>
      {!props.hasToken ? <EmptyState title="Sign in to view recent detections" detail="Your observations are private to your RoutIQ account." action={<button className="ri-small-button" onClick={() => props.onNavigate('Upload & Analyze')}>Open AI workspace</button>}/> :
        props.aiLoading && !props.aiSummary ? <div className="ri-loading-line">Loading recent detections...</div> :
        props.aiError && !props.observations.length ? <InlineError text={props.aiError}/> :
        !props.observations.length ? <EmptyState title="No detections saved yet" detail="Choose a road image and run YOLO detection to create your first observation." action={<button className="ri-small-button" onClick={() => props.onNavigate('Upload & Analyze')}>Upload & Analyze</button>}/> :
        <div className="ri-recent-grid">{props.observations.slice(0, 5).map((item) => <article className="ri-recent-card" key={item.id}><div className="ri-recent-thumb"><span className={`ri-damage-badge ${damageTone(item.damage_class)}`}>{prettyLabel(item.damage_class)}</span><span className="ri-confidence-chip">{(item.confidence * 100).toFixed(1)}%</span><span className="ri-thumb-glyph"><Icon name="road" size={26}/></span></div><div className="ri-recent-card-body"><strong>Observation #{item.id}</strong><span>{item.source_name || 'Uploaded road image'}</span><small><Icon name="clock" size={12}/>{displayDate(item.observed_at || item.created_at)}</small></div></article>)}</div>
      }
    </Panel>
  </>;
}

function donutBackground(entries: [string, number][]): string {
  const colors = ['#e4b72d', '#6fa879', '#b95d45', '#8c897d', '#4e7772'];
  const total = entries.reduce((sum, [, value]) => sum + Number(value), 0);
  if (!total) return '#e8e3d5';

  let progress = 0;
  const parts = entries.map(([, value], index) => {
    const start = progress;
    progress += (Number(value) / total) * 100;
    return `${colors[index % colors.length]} ${start.toFixed(2)}% ${progress.toFixed(2)}%`;
  });

  return `conic-gradient(${parts.join(', ')})`;
}

function damageTone(value: string): string {
  const normalized = value.toLowerCase();

  if (normalized.includes('pothole')) return 'red';
  if (normalized.includes('crack')) return 'amber';
  if (normalized.includes('rutting')) return 'green';

  return 'blue';
}
function MapViewPage(props: {
  currentLocation: Location; setCurrentLocation: (location: Location) => void;
  locationReady: boolean; locationError: string; locationLoading: boolean; onRetryLocation: () => void;
  showSatellite: boolean; setShowSatellite: (value: boolean) => void;
  showMajorRoadsOnly: boolean; setShowMajorRoadsOnly: (value: boolean) => void;
  roadHealthEnabled: boolean; setRoadHealthEnabled: (value: boolean) => void;
  statusFilter: PotholeStatus | 'all'; setStatusFilter: (value: PotholeStatus | 'all') => void;
  severityFilter: PotholeSeverity | 'all'; setSeverityFilter: (value: PotholeSeverity | 'all') => void;
  dateRange?: { start: Date; end: Date }; setDateRange: (value: { start: Date; end: Date } | undefined) => void;
  refreshTrigger: number; refresh: () => void; error: string;
}) {
  const [showLocationMarker, setShowLocationMarker] = useState(true);
  return <>
    <div className="ri-map-view-grid">
      <Panel className="ri-map-large-panel">
        <PanelTitle icon="map" title="Live road map" action={<span className="ri-map-live-label"><i/>Interactive map</span>}/>
        <div className="ri-large-map">{props.locationReady ? <MapComponent location={props.currentLocation} showSatellite={props.showSatellite} showMajorRoadsOnly={props.showMajorRoadsOnly} statusFilter={props.statusFilter} severityFilter={props.severityFilter} dateRange={props.dateRange} refreshTrigger={props.refreshTrigger} roadHealthEnabled={false} showLocationMarker={showLocationMarker}/> : <div className="ri-empty-compact" role="status"><strong>{props.locationLoading ? 'Finding your location...' : 'Map location needed'}</strong><p>{props.locationError || 'Allow location access to center the map on your current position, or search for a location.'}</p><button className="ri-small-button" onClick={props.onRetryLocation}>{props.locationLoading ? 'Requesting location...' : 'Use my current location'}</button></div>}</div>
        <div className="ri-map-legend"><span><i className="ri-legend-dot legacy"/>Existing reports</span><span><i className="ri-legend-dot ai"/>AI observations with GPS</span><span><i className="ri-legend-dot health"/>Road health</span></div>
      </Panel>
      <div className="ri-map-tools">
        <Panel>
          <PanelTitle icon="pin" title="Find a location"/>
          <LocationSearch
            onLocationSelect={(location) => {
              props.setCurrentLocation(location);
              setShowLocationMarker(true);
            }}
            placeholder="Search road, locality, or city..."
          />
          <button
            type="button"
            className="ri-outline-button ri-full-button"
            onClick={() => {
              if (!navigator.geolocation) {
                window.alert("Geolocation is not supported by this browser.");
                return;
              }

              navigator.geolocation.getCurrentPosition(
                (position) => {
                  props.setCurrentLocation({
                    lat: position.coords.latitude,
                    lng: position.coords.longitude,
                    name: "My current location"
                  });
                  setShowLocationMarker(true);
                },
                (error) => window.alert(
                  error.code === error.PERMISSION_DENIED
                    ? "Location permission denied. Allow location access in your browser."
                    : "Could not get your location. Please try again."
                ),
                { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
              );
            }}
          >
            Use my current location
          </button>
                    {/* RoutIQ Google Street View link v1 */}
          <button
            type="button"
            className="ri-outline-button ri-full-button"
            onClick={() => {
              const viewpoint = encodeURIComponent(
                `${props.currentLocation.lat},${props.currentLocation.lng}`
              );
              const url = `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${viewpoint}`;
              window.open(url, '_blank', 'noopener,noreferrer');
            }}
          >
            <Icon name="external" size={15}/>Open Street View
          </button><div className="ri-current-location"><Icon name="locate" size={15}/><div><strong>{props.currentLocation.name}</strong><span>{props.currentLocation.lat.toFixed(5)}, {props.currentLocation.lng.toFixed(5)}</span></div></div>

        </Panel>
        <Panel>
          <PanelTitle icon="sliders" title="Map controls"/>
          <div className="ri-toggle-list">
            <button className={`ri-toggle-row${props.showSatellite ? ' enabled' : ''}`} onClick={() => props.setShowSatellite(!props.showSatellite)}><span><Icon name="map" size={16}/>Satellite imagery</span><i/></button>
            <button className={`ri-toggle-row${props.showMajorRoadsOnly ? ' enabled' : ''}`} onClick={() => props.setShowMajorRoadsOnly(!props.showMajorRoadsOnly)}><span><Icon name="road" size={16}/>Overlay road tiles</span><i/></button>
            <div className="ri-toggle-row ri-toggle-row-disabled" role="note" title="Unavailable until the road-health API returns valid segment data">
              <span><Icon name="activity" size={16}/>Road Health (temporarily unavailable)</span>
              <i/>
            </div>
          </div>
          <label className="ri-field-label">Existing report status<select value={props.statusFilter} onChange={(event) => props.setStatusFilter(event.target.value as PotholeStatus | 'all')}><option value="all">All statuses</option><option value="reported">Reported</option><option value="verified">Verified</option><option value="in_progress">In progress</option><option value="fixed">Fixed</option><option value="closed">Closed</option></select></label>
          <label className="ri-field-label">Severity<select value={props.severityFilter} onChange={(event) => props.setSeverityFilter(event.target.value as PotholeSeverity | 'all')}><option value="all">All severity</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label>
          <div className="ri-date-range-fields">
            <label className="ri-field-label">From date<input type="date" value={props.dateRange ? localDateInput(props.dateRange.start) : ''} onChange={(event) => {
              const start = event.target.value ? new Date(`${event.target.value}T00:00:00`) : null;
              const end = props.dateRange?.end ?? null;
              props.setDateRange(start && end ? { start, end } : undefined);
            }}/></label>
            <label className="ri-field-label">To date<input type="date" value={props.dateRange ? localDateInput(props.dateRange.end) : ''} onChange={(event) => {
              const end = event.target.value ? new Date(`${event.target.value}T23:59:59`) : null;
              const start = props.dateRange?.start ?? null;
              props.setDateRange(start && end ? { start, end } : undefined);
            }}/></label>
            {props.dateRange && <button className="ri-link-button ri-clear-date" onClick={() => props.setDateRange(undefined)}>Clear date filter</button>}
          </div>
          <button className="ri-outline-button ri-full-button" onClick={props.refresh}><Icon name="refresh" size={15}/>Refresh map data</button>
        </Panel>
      </div>
    </div>
    {props.error && <InlineError text={props.error} onRetry={props.refresh}/>}
  </>;
}


function ReportedIssuesPage(props: {
  issues: Pothole[];
  allCount: number;
  stats: PotholeStats | null;
  loading: boolean;
  error: string;
  searchText: string;
  statusFilter: PotholeStatus | 'all';
  severityFilter: PotholeSeverity | 'all';
  setStatusFilter: (value: PotholeStatus | 'all') => void;
  setSeverityFilter: (value: PotholeSeverity | 'all') => void;
  refresh: () => void;
  onOpenMap: (issue: Pothole) => void;
  observations: Array<{
    id: number;
    damage_class: string;
    confidence: number;
    latitude: number | string | null;
    longitude: number | string | null;
    assessment_status: string;
    observed_at: string;
    created_at?: string;
    source_name?: string;
  }>;
  aiLoading: boolean;
  reviewError: string;
  reviewNotice: string;
  refreshAI: () => void;
}) {
  const [activeTab, setActiveTab] = useState<'ai' | 'legacy'>('ai');
  const gpsMappedCount = props.observations.filter(
    (item) => item.latitude != null && item.longitude != null,
  ).length;

  const needsReviewCount = props.observations.filter((item) => {
    const value = String(item.assessment_status || 'unknown').toLowerCase();
    return !['damage_persists', 'appears_resolved', 'new_damage'].includes(value);
  }).length;

  return <>
    <div className="ri-issues-tabs" role="tablist" aria-label="Issue data sources">
      <button
        type="button"
        role="tab"
        aria-selected={activeTab === 'ai'}
        className="ri-issues-tab"
        onClick={() => setActiveTab('ai')}
      >
        AI observations <span>{props.observations.length}</span>
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={activeTab === 'legacy'}
        className="ri-issues-tab"
        onClick={() => setActiveTab('legacy')}
      >
        Legacy reports <span>{safeCount(props.stats?.total_reports)}</span>
      </button>
    </div>

    {activeTab === 'legacy' ? <>
      <div className="ri-mini-stats">
        <div><span>All reports</span><strong>{safeCount(props.stats?.total_reports)}</strong></div>
        <div><span>Potholes recorded</span><strong>{safeCount(props.stats?.total_potholes)}</strong></div>
        <div><span>In progress</span><strong>{safeCount(props.stats?.by_status?.in_progress)}</strong></div>
        <div><span>Marked fixed</span><strong>{safeCount(props.stats?.by_status?.fixed)}</strong></div>
      </div>

      <Panel>
        <div className="ri-table-toolbar">
          <div>
            <PanelTitle icon="issues" title="Reported road issues" />
            <p>{props.issues.length} result(s) of {props.allCount} reports in the current database.</p>
          </div>
          <div className="ri-table-actions">
            <label className="ri-compact-select">
              Status
              <select
                value={props.statusFilter}
                onChange={(event) => props.setStatusFilter(event.target.value as PotholeStatus | 'all')}
              >
                <option value="all">All</option>
                <option value="reported">Reported</option>
                <option value="verified">Verified</option>
                <option value="in_progress">In progress</option>
                <option value="fixed">Fixed</option>
                <option value="closed">Closed</option>
              </select>
            </label>
            <label className="ri-compact-select">
              Severity
              <select
                value={props.severityFilter}
                onChange={(event) => props.setSeverityFilter(event.target.value as PotholeSeverity | 'all')}
              >
                <option value="all">All</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </label>
            <button type="button" className="ri-outline-button" onClick={props.refresh}>
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </div>
        </div>

        {props.error && <InlineError text={props.error} onRetry={props.refresh} />}

        {props.loading ? (
          <div className="ri-loading-line">Loading legacy road reports...</div>
        ) : !props.issues.length ? (
          <EmptyState
            title={props.allCount ? 'No issues match these filters' : 'No existing road reports yet'}
            detail={props.allCount
              ? 'Adjust the status, severity, or search filter.'
              : 'The legacy road-report table is empty. AI detections are available in the AI observations tab.'}
          />
        ) : (
          <div className="ri-table-wrap">
            <table className="ri-table">
              <thead>
                <tr>
                  <th>Issue</th><th>Location</th><th>Severity</th><th>Reports</th><th>Status</th><th>Reported at</th><th>Action</th>
                </tr>
              </thead>
              <tbody>
                {props.issues.map((issue) => (
                  <tr key={issue.id}>
                    <td><span className="ri-table-id">#{issue.id}</span><strong>Pothole report</strong></td>
                    <td>
                      <span className="ri-location-name">{issue.location_string || 'Location not named'}</span>
                      <small>{issue.latitude}, {issue.longitude}</small>
                    </td>
                    <td><span className={`ri-pill ${issue.severity}`}>{prettyLabel(issue.severity)}</span></td>
                    <td>{safeCount(issue.num_potholes)}</td>
                    <td><span className={`ri-status-pill ${issue.status}`}>{prettyLabel(issue.status)}</span></td>
                    <td>{displayDate(issue.timestamp || issue.created_at)}</td>
                    <td><button type="button" className="ri-small-button" onClick={() => props.onOpenMap(issue)}>View map</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </> : <>
      <div className="ri-mini-stats">
        <div><span>AI observations</span><strong>{props.observations.length}</strong></div>
        <div><span>GPS mapped</span><strong>{gpsMappedCount}</strong></div>
        <div><span>Needs review</span><strong>{needsReviewCount}</strong></div>
        <div><span>Legacy reports</span><strong>{safeCount(props.stats?.total_reports)}</strong></div>
      </div>

      <Panel>
        <div className="ri-table-toolbar">
          <div>
            <PanelTitle icon="activity" title="AI road observations" />
            <p>Saved detections from your account. Review status is stored separately from model confidence.</p>
          </div>
          <button type="button" className="ri-outline-button" onClick={props.refreshAI}>
            <Icon name="refresh" size={15} /> Refresh observations
          </button>
        </div>

        {props.reviewNotice && <div className="ri-inline-success" role="status">{props.reviewNotice}</div>}
        {props.reviewError && <InlineError text={props.reviewError} />}

        {props.aiLoading ? (
          <div className="ri-loading-line">Loading AI observations...</div>
        ) : !props.observations.length ? (
          <EmptyState
            title="No AI observations yet"
            detail="Use Upload & Analyze to inspect a road image. Successful detections saved to your account will appear here."
          />
        ) : (
          <div className="ri-table-wrap">
            <table className="ri-table">
              <thead>
                <tr>
                  <th>Observation</th>
                  <th>Detection confidence</th>
                  <th>Photo location</th>
                  <th>Automated triage</th>
                  <th>Observed at</th>
                </tr>
              </thead>
              <tbody>
                {props.observations.map((item) => {
                  return (
                    <tr key={item.id}>
                      <td>
                        <span className="ri-table-id">#{item.id}</span>
                        <strong>{prettyLabel(item.damage_class)}</strong>
                        <small>{item.source_name || 'Road image'}</small>
                      </td>
                      <td>
                        <div className="ri-confidence-meter">
                          <span style={{ width: `${Math.max(0, Math.min(100, Number(item.confidence) * 100))}%` }} />
                        </div>
                        <small>{(Number(item.confidence) * 100).toFixed(1)}%</small>
                      </td>
                      <td>
                        {item.latitude != null && item.longitude != null
                          ? `${item.latitude}, ${item.longitude}`
                          : 'Not provided'}
                      </td>
                      <td>
                        <span className={`ri-status-pill ${Number(item.confidence) < 0.5 ? 'uncertain' : 'unknown'}`}>
                          {Number(item.confidence) < 0.5 ? 'Needs review' : 'Detected · unverified'}
                        </span>
                        <small>{Number(item.confidence) < 0.5 ? 'Below the 50% triage threshold' : 'Awaiting repair verification'}</small>
                      </td>
                      <td>{displayDate(item.observed_at || item.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <p className="ri-footnote">
          Automated triage uses a configurable confidence threshold. Detection confidence is not model accuracy, and a detection alone cannot prove that a repair occurred.
        </p>
      </Panel>
    </>}
  </>;
}


function SessionEvidencePreview({ sessionId, title, sourceName }: {
  sessionId: number | null;
  title: string;
  sourceName: string;
}) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [message, setMessage] = useState('Loading retained image evidence…');

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setImageUrl(null);
    setMessage(sessionId ? 'Loading retained image evidence…' : 'Select an inspection session with retained image evidence.');

    if (!sessionId) return () => { cancelled = true; };
    const token = tokenValue();
    if (!token) {
      setMessage('Sign in to view private inspection images.');
      return () => { cancelled = true; };
    }

    const extension = sourceName.match(/\.(jpe?g|png|webp)(?:$|[?#])/i)?.[1]?.toLowerCase();
    const imageMime: Record<string, string> = {
      jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp',
    };

    void (async () => {
      try {
        const response = await fetch(`${API_ROOT}/road-observations/sessions/${sessionId}/evidence/`, {
          headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
          cache: 'no-store',
        });
        if (!response.ok) {
          if (response.status === 404 || response.status === 410) {
            throw new Error('No retained photo is available for this session. Older uploads cannot be reconstructed.');
          }
          throw new Error(`Private image could not be loaded (HTTP ${response.status}).`);
        }
        const raw = await response.blob();
        const mime = raw.type.startsWith('image/') ? raw.type : (imageMime[extension ?? ''] ?? '');
        if (!mime) throw new Error('The image format could not be identified for preview.');
        objectUrl = URL.createObjectURL(new Blob([await raw.arrayBuffer()], { type: mime }));
        if (!cancelled) {
          setImageUrl(objectUrl);
          setMessage('');
        } else {
          URL.revokeObjectURL(objectUrl);
        }
      } catch (error) {
        if (!cancelled) setMessage(error instanceof Error ? error.message : 'Image evidence could not be loaded.');
      }
    })();

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [sessionId, sourceName]);

  return <div className="ri-session-image-card">
    <div className="ri-session-image-heading"><strong>{title}</strong><small>{sourceName || 'Inspection image'}</small></div>
    {imageUrl ? <img src={imageUrl} alt={title} /> : <div className="ri-session-image-empty">{message}</div>}
  </div>;
}

function SessionEvidenceComparisonPanel({ hasToken }: { hasToken: boolean }) {
  const [sessions, setSessions] = useState<SessionEvidenceRecord[]>([]);
  const [beforeId, setBeforeId] = useState('');
  const [afterId, setAfterId] = useState('');
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [reloadCount, setReloadCount] = useState(0);
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState('');
  const [result, setResult] = useState<SessionEvidenceComparisonResponse | null>(null);

  useEffect(() => {
    let active = true;
    if (!hasToken) return () => { active = false; };
    setLoadingSessions(true);
    setLoadError('');
    void (async () => {
      try {
        const payload = await aiFetch<unknown>('/road-observations/sessions/');
        const rows = Array.isArray(payload)
          ? payload as SessionEvidenceRecord[]
          : (payload && typeof payload === 'object' && Array.isArray((payload as Record<string, unknown>).results)
            ? (payload as { results: SessionEvidenceRecord[] }).results
            : []);
        const available = rows
          .filter((session) => session.evidence_available === true && Number.isFinite(Number(session.id)))
          .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
        if (!active) return;
        setSessions(available);
        setBeforeId(available[0] ? String(available[0].id) : '');
        setAfterId(available[1] ? String(available[1].id) : '');
        setResult(null);
      } catch (error) {
        if (active) setLoadError(error instanceof Error ? error.message : 'Inspection sessions could not be loaded.');
      } finally {
        if (active) setLoadingSessions(false);
      }
    })();
    return () => { active = false; };
  }, [hasToken, reloadCount]);

  const before = sessions.find((session) => String(session.id) === beforeId);
  const after = sessions.find((session) => String(session.id) === afterId);
  const chronological = Boolean(before && after && new Date(before.created_at).getTime() < new Date(after.created_at).getTime());

  const runComparison = async () => {
    if (!before || !after || before.id === after.id || !chronological) {
      setCompareError('Choose two different saved sessions in chronological order: an earlier reference image and a later comparison image.');
      return;
    }
    setComparing(true);
    setCompareError('');
    setResult(null);
    try {
      const response = await aiFetch<SessionEvidenceComparisonResponse>('/road-observations/session-evidence-review/', {
        method: 'POST',
        body: JSON.stringify({ session_a_id: before.id, session_b_id: after.id }),
      });
      setResult(response);
    } catch (error) {
      setCompareError(error instanceof Error ? error.message : 'The image comparison could not be completed.');
    } finally {
      setComparing(false);
    }
  };

  const imageResult = result?.image_comparison;
  const visualLabel = imageResult?.status === 'candidate_visual_similarity'
    ? 'Visual regions look broadly similar'
    : imageResult?.status === 'candidate_visual_change'
      ? 'Visual differences detected'
      : imageResult?.status === 'mixed_visual_evidence'
        ? 'Mixed visual evidence'
        : 'Insufficient visual evidence';

  return <Panel>
    <PanelTitle icon="activity" title="Before / after image evidence" />
    <p className="ri-muted">Compare retained images from two inspection sessions, including a later session with zero detections. Visual differences are review cues, not proof of repair.</p>
    {loadError && <InlineError text={loadError} onRetry={() => setReloadCount((value) => value + 1)} />}
    {loadingSessions ? <div className="ri-loading-line">Loading private inspection images…</div> : sessions.length < 2 ?
      <EmptyState title="Two retained inspection images are needed" detail="Upload at least two images. RoutIQ now retains each inspected image privately for a limited period, including sessions where no damage is detected." action={<button className="ri-outline-button" onClick={() => setReloadCount((value) => value + 1)}>Refresh sessions</button>} /> :
      <>
        <div className="ri-review-form">
          <label className="ri-field-label">Before / reference session
            <select value={beforeId} onChange={(event) => { const nextId = event.target.value; setBeforeId(nextId); if (afterId === nextId) setAfterId(String(sessions.find((session) => String(session.id) !== nextId)?.id ?? '')); setResult(null); }}>
              {sessions.map((session) => <option key={session.id} value={session.id}>#{session.id} · {displayDate(session.created_at)} · {session.title || session.source_kind}</option>)}
            </select>
          </label>
          <label className="ri-field-label">After / comparison session
            <select value={afterId} onChange={(event) => { setAfterId(event.target.value); setResult(null); }}>
              {sessions.filter((session) => String(session.id) !== beforeId).map((session) => <option key={session.id} value={session.id}>#{session.id} · {displayDate(session.created_at)} · {session.title || session.source_kind}</option>)}
            </select>
          </label>
        </div>
        <div className="ri-before-after-grid">
          <SessionEvidencePreview sessionId={before ? before.id : null} title="Before · reference image" sourceName={before?.title ?? ''} />
          <SessionEvidencePreview sessionId={after ? after.id : null} title="After · comparison image" sourceName={after?.title ?? ''} />
        </div>
        {before && after && !chronological && <p className="ri-muted">The after image must come from a later inspection session than the before image.</p>}
        {compareError && <InlineError text={compareError} />}
        <button className="ri-primary-button" onClick={runComparison} disabled={comparing || !before || !after || before.id === after.id || !chronological}>
          {comparing ? 'Comparing image evidence…' : 'Compare before / after images'}
        </button>
      </>
    }
    {result && imageResult && <div className={`ri-visual-comparison-result ${imageResult.status === 'insufficient_evidence' ? 'abstained' : ''}`}>
      <div className="ri-result-heading"><span className="ri-result-icon"><Icon name={imageResult.status === 'insufficient_evidence' ? 'alert' : 'activity'} size={20}/></span><div><small>VISUAL EVIDENCE COMPARISON #{result.comparison_id}</small><h3>{visualLabel}</h3></div></div>
      <p>{imageResult.explanation}</p>
      <div className="ri-result-metrics">
        <div><span>Structural similarity</span><strong>{imageResult.metrics?.structural_similarity == null ? 'Unavailable' : `${(imageResult.metrics.structural_similarity * 100).toFixed(1)}%`}</strong></div>
        <div><span>Changed pixels</span><strong>{imageResult.metrics?.changed_pixel_percent == null ? 'Unavailable' : `${imageResult.metrics.changed_pixel_percent.toFixed(1)}%`}</strong></div>
        <div><span>Shared image area</span><strong>{imageResult.metrics?.overlap_percent == null ? 'Unavailable' : `${imageResult.metrics.overlap_percent.toFixed(1)}%`}</strong></div>
      </div>
      <p className="ri-research-warning">Reference detections: {result.detections_a}; comparison detections: {result.detections_b}. This is an uncalibrated computer-vision review aid, not an automated repair verdict. Viewpoint, lighting, weather, water, shadows and traffic can change image scores. A reviewer must confirm any repair decision.</p>
      <p className="ri-muted">Repair verification: not inferred automatically.</p>
    </div>}
  </Panel>;
}

function RepairVerificationPage(props: {
  hasToken: boolean; observations: Observation[]; mappedObservations: Observation[]; aiLoading: boolean; aiSummary: AISummary | null; aiError: string;
  gpsEditor: { id: number; lat: string; lon: string } | null; setGpsEditor: (value: { id: number; lat: string; lon: string } | null) => void;
  gpsBusy: boolean; onUseCurrentLocation: (id: number) => void; saveGps: () => void; reviewNotice: string; reviewError: string;
  reviewFirst: string; setReviewFirst: (value: string) => void; reviewSecond: string; setReviewSecond: (value: string) => void;
  reviewBusy: boolean; reviewResult: TemporalResult | null; compareEvidence: () => void; flagForReview: (id: number) => void;
  refresh: () => void; exportCsv: () => void; exportGeoJson: () => void; onSignIn: () => void;
}) {
  if (!props.hasToken) return <Panel><EmptyState title="Sign in to review saved evidence" detail="RoutIQ observations are private to an authenticated account. Sign in from the AI Detection Studio; this screen does not bypass authentication." action={<button className="ri-primary-button" onClick={props.onSignIn}>Open AI Detection Studio</button>}/></Panel>;
  const resultLabel = props.reviewResult?.decision === 'same_damage' ? 'Possible repeat sighting' : props.reviewResult?.decision === 'different_damage' ? 'Different-damage candidate' : 'Insufficient evidence — manual review required';
  const selectedReference = props.mappedObservations.find(
    (item) => String(item.id) === props.reviewFirst
  );

  const comparisonOptions = props.mappedObservations.filter(
    (item) =>
      Boolean(selectedReference) &&
      item.id !== selectedReference?.id &&
      !isSameInspectionPass(selectedReference as Observation, item)
  );
  return <>
    <div className="ri-mini-stats"><div><span>Saved observations</span><strong>{safeCount(props.aiSummary?.total_observations)}</strong></div><div><span>GPS mapped</span><strong>{safeCount(props.aiSummary?.mapped_observations)}</strong></div><div><span>Inspection sessions</span><strong>{safeCount(props.aiSummary?.sessions)}</strong></div><div><span>Needs review</span><strong>{safeCount(props.aiSummary?.by_status?.uncertain ?? 0)}</strong></div></div>
    {props.reviewError && <InlineError text={props.reviewError}/>}
    {props.reviewNotice && <div className="ri-inline-notice"><Icon name="checkCircle" size={16}/>{props.reviewNotice}</div>}
    {props.aiError && <InlineError text={props.aiError} onRetry={props.refresh}/>}
    <SessionEvidenceComparisonPanel hasToken={props.hasToken} />
    <div className="ri-review-grid">
      <Panel>
        <PanelTitle icon="verify" title="Repeat-pass evidence review"/>
        <p className="ri-muted">Compare two saved, GPS-mapped observations. Weak or conflicting evidence should abstain and request manual review.</p>
        {props.mappedObservations.length < 2 ? <EmptyState title="Two mapped observations are needed" detail={`This account has ${props.mappedObservations.length} GPS-mapped observation(s). Add verified photo coordinates to a saved record, then upload or record a separate observation for another pass.`}/> :
          <div className="ri-review-form">
            <label className="ri-field-label">
              Reference observation
              <select
                value={props.reviewFirst}
                onChange={(event) => props.setReviewFirst(event.target.value)}
              >
                <option value="">Select reference</option>
                {props.mappedObservations.map((item) => (
                  <option key={item.id} value={item.id}>
                    #{item.id} · {prettyLabel(item.damage_class)} · {displayDate(item.observed_at)} · {item.source_name || 'source unknown'}
                  </option>
                ))}
              </select>
            </label>

            <label className="ri-field-label">
              Comparison observation
              <select
                value={props.reviewSecond}
                onChange={(event) => props.setReviewSecond(event.target.value)}
              >
                <option value="">Select comparison</option>
                {comparisonOptions.map((item) => (
                  <option key={item.id} value={item.id}>
                    #{item.id} · {prettyLabel(item.damage_class)} · {displayDate(item.observed_at)} · {item.source_name || 'source unknown'}
                  </option>
                ))}
              </select>
            </label>

            {comparisonOptions.length === 0 && (
              <p className="ri-muted">
                No separate inspection pass is available for this reference. Save another observation from a later pass before comparing.
              </p>
            )}

            <button
              className="ri-primary-button"
              onClick={props.compareEvidence}
              disabled={
                props.reviewBusy ||
                !props.reviewFirst ||
                !props.reviewSecond ||
                props.reviewFirst === props.reviewSecond ||
                !comparisonOptions.some((item) => String(item.id) === props.reviewSecond)
              }
            >
              {props.reviewBusy ? 'Reviewing evidence…' : 'Compare observations'}
            </button>
          </div>
        }
        {props.reviewResult && <div className={`ri-review-result ${props.reviewResult.abstained ? 'abstained' : ''}`}><div className="ri-result-heading"><span className="ri-result-icon"><Icon name={props.reviewResult.abstained ? 'alert' : 'checkCircle'} size={20}/></span><div><small>COMPARISON #{props.reviewResult.match_id}</small><h3>{resultLabel}</h3></div></div><div className="ri-result-metrics"><div><span>Heuristic match score</span><strong>{props.reviewResult.score == null ? 'Not scoreable' : `${(props.reviewResult.score * 100).toFixed(1)}%`}</strong></div><div><span>GPS separation</span><strong>{props.reviewResult.distance_m == null ? 'Unavailable' : `${props.reviewResult.distance_m.toFixed(1)} m`}</strong></div><div><span>Time gap</span><strong>{props.reviewResult.temporal_gap_hours == null ? 'Unavailable' : `${props.reviewResult.temporal_gap_hours.toFixed(1)} h`}</strong></div></div><div className="ri-quality-row"><span>Observation A quality <b>{Math.round(props.reviewResult.quality_a.score * 100)}%</b></span><span>Observation B quality <b>{Math.round(props.reviewResult.quality_b.score * 100)}%</b></span></div>{props.reviewResult.reasons?.length > 0 && <ul className="ri-reason-list">{props.reviewResult.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>}<p className="ri-research-warning">This is a heuristic candidate comparison, not calibrated probability or proof of repair. Missing detections do not establish that road damage was repaired.</p></div>}
      </Panel>
      <Panel>
        <PanelTitle icon="activity" title="Evidence quality summary"/>
        <div className="ri-quality-summary"><div><span className="ri-quality-bullet gps"/><div><strong>GPS coverage</strong><small>Coordinates only count when they are actually stored.</small></div><b>{props.aiSummary?.total_observations ? `${Math.round((Number(props.aiSummary.mapped_observations) / Number(props.aiSummary.total_observations)) * 100)}%` : '—'}</b></div><div><span className="ri-quality-bullet photo"/><div><strong>Image source</strong><small>Uploaded filename and model metadata are retained on observations.</small></div><b>{props.aiSummary?.total_observations ? 'Recorded' : '—'}</b></div><div><span className="ri-quality-bullet review"/><div><strong>Manual review</strong><small>Uncertain assessments remain visible for further inspection.</small></div><b>{safeCount(props.aiSummary?.by_status?.uncertain ?? 0)}</b></div></div>
        <div className="ri-export-card"><strong>Export observation evidence</strong><p>Download actual saved rows for review or external GIS analysis.</p><div className="ri-button-row"><button className="ri-outline-button" onClick={props.exportCsv} disabled={!props.observations.length}><Icon name="download" size={15}/>CSV</button><button className="ri-outline-button" onClick={props.exportGeoJson} disabled={!props.mappedObservations.length}><Icon name="map" size={15}/>GeoJSON</button><button className="ri-outline-button" onClick={props.refresh}><Icon name="refresh" size={15}/>Refresh</button></div></div>
      </Panel>
    </div>
    <Panel>
      <div className="ri-table-toolbar"><div><PanelTitle icon="file" title="Saved observations"/><p>{props.observations.length} observation(s) from this RoutIQ account</p></div></div>
      {props.aiLoading ? <div className="ri-loading-line">Loading observations...</div> : !props.observations.length ? <EmptyState title="No saved observations" detail="Run AI detection first. Successful detections should be returned by the Django observation API."/> :
        <div className="ri-table-wrap"><table className="ri-table"><thead><tr><th>Observation</th><th>Confidence</th><th>Coordinates</th><th>Status</th><th>Observed at</th><th>Action</th></tr></thead><tbody>{props.observations.map((item) => <tr key={item.id}><td><span className="ri-table-id">#{item.id}</span><strong>{prettyLabel(item.damage_class)}</strong><small>{item.source_name || 'Road image'}</small></td><td><div className="ri-confidence-meter"><span style={{ width: `${Math.max(0, Math.min(100, item.confidence * 100))}%` }}/></div><small>{(item.confidence * 100).toFixed(1)}%</small></td><td>{props.gpsEditor?.id === item.id ? <div className="ri-gps-editor"><input aria-label="Photo latitude" type="number" min="-90" max="90" step="any" placeholder="Latitude" value={props.gpsEditor.lat} onChange={(event) => props.setGpsEditor({ id: item.id, lat: event.target.value, lon: props.gpsEditor?.lon ?? '' })}/><input aria-label="Photo longitude" type="number" min="-180" max="180" step="any" placeholder="Longitude" value={props.gpsEditor.lon} onChange={(event) => props.setGpsEditor({ id: item.id, lat: props.gpsEditor?.lat ?? '', lon: event.target.value })}/><div className="ri-button-row"><button className="ri-small-button primary" disabled={props.gpsBusy} onClick={props.saveGps}>{props.gpsBusy ? 'Saving...' : 'Save GPS'}</button><button className="ri-small-button" type="button" disabled={props.gpsBusy} onClick={() => props.onUseCurrentLocation(item.id)}>Use Current Location</button><button className="ri-small-button" onClick={() => props.setGpsEditor(null)}>Cancel</button></div></div> : <div className="ri-coordinate-cell"><span>{item.latitude != null && item.longitude != null ? `${item.latitude}, ${item.longitude}` : 'Not provided'}</span><button className="ri-small-button" onClick={() => props.setGpsEditor({ id: item.id, lat: item.latitude == null ? '' : String(item.latitude), lon: item.longitude == null ? '' : String(item.longitude) })}>{item.latitude != null && item.longitude != null ? 'Edit GPS' : 'Add GPS'}</button></div>}</td><td><span className={`ri-status-pill ${item.assessment_status}`}>{prettyLabel(item.assessment_status)}</span></td><td>{displayDate(item.observed_at || item.created_at)}</td><td><button className="ri-small-button" onClick={() => props.flagForReview(item.id)}>Flag for review</button></td></tr>)}</tbody></table></div>
      }
      <p className="ri-footnote">Only set coordinates that represent where the photo was captured. Sample coordinates are not ground truth.</p>
        </Panel>
      </>;
}

function AnalyticsPage(props: {
  dateWindow: string;
  publicLoading: boolean;
  hasToken: boolean;
  aiSummary: AISummary | null;
  observations: Observation[];
  classEntries: [string, number][];
  maxClassValue: number;
  statusEntries: [string, number][];
  potholeStats: PotholeStats | null;
  roadHealth: RoadHealthData[];
  publicError: string;
  aiError: string;
  loading: boolean;
  onRefresh: () => void;
  onUpload: () => void;
}) {
  const days = Number(props.dateWindow);
  const now = Date.now();
  const cutoff = days > 0 ? now - days * 86400000 : Number.NEGATIVE_INFINITY;

  const filteredObservations = props.observations.filter((item) => {
    const timestamp = new Date(item.observed_at || item.created_at || "").getTime();
    return Number.isFinite(timestamp) && timestamp >= cutoff && timestamp <= now;
  });

  const mappedObservations = filteredObservations.filter((item) => {
    if (item.latitude == null || item.longitude == null) return false;
    const lat = Number(item.latitude);
    const lon = Number(item.longitude);
    return Number.isFinite(lat) && Number.isFinite(lon)
      && lat >= -90 && lat <= 90
      && lon >= -180 && lon <= 180
      && !(lat === 0 && lon === 0);
  });

  const classCounts = new Map<string, number>();
  const statusCounts = new Map<string, number>();

  for (const item of filteredObservations) {
    const className = String(item.damage_class || "unknown").trim().toLowerCase().replace(/\s+/g, "_");
    const statusName = String(item.assessment_status || "unknown").trim().toLowerCase().replace(/\s+/g, "_");
    classCounts.set(className, (classCounts.get(className) ?? 0) + 1);
    statusCounts.set(statusName, (statusCounts.get(statusName) ?? 0) + 1);
  }

  const filteredClasses = [...classCounts.entries()].sort((a, b) => b[1] - a[1]);
  const filteredStatuses = [...statusCounts.entries()].sort((a, b) => b[1] - a[1]);
  const maxClass = Math.max(1, ...filteredClasses.map(([, count]) => count));

  const validConfidence = filteredObservations
    .filter((item) => item.confidence != null)
    .map((item) => Number(item.confidence))
    .filter((value) => Number.isFinite(value) && value >= 0 && value <= 1);

  const averageConfidence = validConfidence.length
    ? validConfidence.reduce((sum, value) => sum + value, 0) / validConfidence.length
    : null;
  const averageConfidencePercent = averageConfidence === null ? 0 : averageConfidence * 100;
  const atLeastHalf = validConfidence.filter((value) => value >= 0.5).length;

  const periodLabel = days === 7 ? "Last 7 days"
    : days === 30 ? "Last 30 days"
    : days === 90 ? "Last 90 days"
    : "All time";

  const activity = analyticsActivityBuckets(filteredObservations, days);
  const maxActivity = Math.max(1, ...activity.map((item) => item.value));

  return <>
    {(props.publicError || (props.hasToken && props.aiError)) &&
      <InlineError
        text={[props.publicError, props.hasToken ? props.aiError : ""].filter(Boolean).join(" · ")}
        onRetry={props.onRefresh}
      />
    }

    <div className="ri-stats-grid">
      <StatCard
        title="AI observations"
        value={!props.hasToken ? "Sign in" : props.loading ? "…" : safeCount(filteredObservations.length)}
        subtitle={`Saved records · ${periodLabel}`}
        icon="activity"
        tone="gold"
      />
      <StatCard
        title="GPS mapped"
        value={!props.hasToken ? "—" : props.loading ? "…" : safeCount(mappedObservations.length)}
        subtitle="Valid saved coordinates"
        icon="pin"
        tone="green"
      />
      <StatCard
        title="Legacy pothole reports"
        value={props.publicLoading ? "…" : safeCount(props.potholeStats?.total_reports)}
        subtitle="Separate legacy dataset"
        icon="road"
        tone="graphite"
      />
      <StatCard
        title="Road-health segments"
        value={safeCount(props.roadHealth.length)}
        subtitle="Segments stored by the backend"
        icon="analytics"
        tone="red"
      />
    </div>

    <div className="ri-analytics-grid">
      <Panel>
        <PanelTitle icon="analytics" title="Damage class distribution" />
        {!props.hasToken ? (
          <EmptyState title="Sign in required" detail="AI observations are private to the signed-in account." action={<button className="ri-small-button" onClick={props.onUpload}>Open AI workspace</button>} />
        ) : props.loading && !props.observations.length ? (
          <div className="ri-loading-line">Loading saved observations…</div>
        ) : !filteredClasses.length ? (
          <EmptyState title="No observations in this period" detail={`No saved observations fall within ${periodLabel.toLowerCase()}. Change the date range or upload a road image.`} action={<button className="ri-small-button" onClick={props.onUpload}>Upload image</button>} />
        ) : (
          <div className="ri-bar-list">
            {filteredClasses.map(([key, count], index) => (
              <div className="ri-bar-item" key={key}>
                <div><span>{prettyLabel(key)}</span><strong>{safeCount(count)}</strong></div>
                <div className="ri-bar-track">
                  <i className={`c${index % 5}`} style={{ width: `${count / maxClass * 100}%` }} />
                </div>
                <small>{(count / filteredObservations.length * 100).toFixed(1)}% of observations</small>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel>
        <PanelTitle icon="checkCircle" title="Observation review status" />
        {!props.hasToken ? (
          <EmptyState title="Sign in required" detail="Sign in to view private review-state counts." />
        ) : !filteredStatuses.length ? (
          <EmptyState title="No review states in this period" detail="Saved status counts will appear after observations are recorded." />
        ) : (
          <div className="ri-health-rows">
            {filteredStatuses.map(([status, count]) => (
              <div className="ri-health-row" key={status}>
                <span className={`ri-health-dot ${status === "uncertain" ? "warning" : "good"}`} />
                <span>{prettyLabel(status)}</span>
                <strong>{safeCount(count)}</strong>
              </div>
            ))}
          </div>
        )}
        <p className="ri-analytics-note">Status totals are calculated from saved observations in the selected period.</p>
      </Panel>

      <Panel>
        <PanelTitle
          icon="trend"
          title={days > 0 && days <= 30
            ? `Daily observation activity · ${periodLabel}`
            : days === 90
              ? "Monthly activity · Last 90 days"
              : "Monthly activity · Recent 12 months"}
        />
        {!props.hasToken ? (
          <EmptyState title="Sign in required" detail="The activity chart uses account-specific observations." />
        ) : !filteredObservations.length ? (
          <EmptyState title="No activity in this period" detail="There are no saved observations for this selected range." />
        ) : (
          <div className="ri-analytics-trend-scroll">
            <div
              className="ri-analytics-trend"
              style={{
                minWidth: `${Math.max(100, activity.length * 25)}px`,
                gridTemplateColumns: `repeat(${activity.length}, minmax(20px, 1fr))`
              }}
            >
              {activity.map((point, index) => (
                <div className="ri-analytics-trend-col" key={point.key} title={`${point.fullLabel}: ${point.value} observation(s)`}>
                  <div className="ri-analytics-trend-track">
                    <div
                      className="ri-analytics-trend-bar"
                      style={{ height: point.value ? `${Math.max(7, point.value / maxActivity * 100)}%` : "0%" }}
                    />
                  </div>
                  <span>{point.label || (index % 5 === 0 ? point.fullLabel : "")}</span>
                  <small>{point.value}</small>
                </div>
              ))}
            </div>
          </div>
        )}
        <p className="ri-analytics-note">
          The 7- and 30-day views use daily buckets. The 90-day view uses monthly buckets; All time shows the recent 12 months in this chart while its total uses all returned records.
        </p>
      </Panel>

      <Panel>
        <PanelTitle icon="activity" title="Detection confidence summary" />
        {!props.hasToken ? (
          <EmptyState title="Sign in required" detail="Confidence summaries use your saved detections." />
        ) : !validConfidence.length ? (
          <EmptyState title="No confidence values available" detail="Successful detections with confidence values will appear here." />
        ) : (
          <div className="ri-confidence-summary">
            <div>
              <span>Average detector confidence</span>
              <strong>{averageConfidencePercent.toFixed(1)}%</strong>
              <div className="ri-bar-track">
                <i style={{ width: `${averageConfidencePercent}%` }} />
              </div>
            </div>
            <div>
              <span>At least 50% confidence</span>
              <strong>{atLeastHalf} / {validConfidence.length}</strong>
              <div className="ri-bar-track">
                <i style={{ width: `${atLeastHalf / validConfidence.length * 100}%` }} />
              </div>
            </div>
            <p className="ri-analytics-note">Detector confidence is not equivalent to model accuracy, precision, recall or mAP.</p>
          </div>
        )}
      </Panel>

    </div>

  </>;
}

function analyticsActivityBuckets(
  items: Observation[],
  days: number
): { key: string; label: string; fullLabel: string; value: number }[] {
  const buckets: { key: string; label: string; fullLabel: string; value: number }[] = [];
  const today = new Date();

  if (days > 0 && days <= 30) {
    const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    for (let offset = days - 1; offset >= 0; offset -= 1) {
      const date = new Date(start);
      date.setDate(start.getDate() - offset);
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
      buckets.push({
        key,
        label: days === 7 ? date.toLocaleDateString(undefined, { weekday: "short" }) : "",
        fullLabel: date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
        value: 0
      });
    }

    for (const item of items) {
      const timestamp = new Date(item.observed_at || item.created_at || "").getTime();
      if (!Number.isFinite(timestamp)) continue;
      const date = new Date(timestamp);
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
      const bucket = buckets.find((entry) => entry.key === key);
      if (bucket) bucket.value += 1;
    }
    return buckets;
  }

  const monthCount = days === 90 ? 3 : 12;
  for (let offset = monthCount - 1; offset >= 0; offset -= 1) {
    const date = new Date(today.getFullYear(), today.getMonth() - offset, 1);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    buckets.push({
      key,
      label: date.toLocaleDateString(undefined, { month: "short" }),
      fullLabel: date.toLocaleDateString(undefined, { month: "long", year: "numeric" }),
      value: 0
    });
  }

  for (const item of items) {
    const timestamp = new Date(item.observed_at || item.created_at || "").getTime();
    if (!Number.isFinite(timestamp)) continue;
    const date = new Date(timestamp);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    const bucket = buckets.find((entry) => entry.key === key);
    if (bucket) bucket.value += 1;
  }
  return buckets;
}


function SettingsPage(props: { hasToken: boolean; userLabel: string; aiError: string; publicError: string; aiSummary: AISummary | null; loading: boolean; detectorReadiness: DetectorReadiness | null; detectorReadinessLoading: boolean; detectorReadinessError: string; onRefresh: () => void; onSignOut: () => void; onSignIn: () => void }) {
  return <>
    <Panel><PanelTitle icon="settings" title="Workspace configuration"/><div className="ri-settings-grid"><div className="ri-setting-row"><span>Application</span><strong>RoutIQ — Intelligent Road Infrastructure Analytics</strong><small>React + TypeScript + Vite frontend</small></div><div className="ri-setting-row"><span>Primary backend</span><strong>Django REST Framework</strong><small>Local API proxy configured through Vite</small></div><div className="ri-setting-row"><span>Vision service</span><strong>FastAPI + YOLO</strong><small>Inference is requested by the Django vision client; this screen does not claim model health unless inference succeeds.</small></div><div className="ri-setting-row"><span>Database</span><strong>RoutIQ main SQLite database</strong><small>Actual path is controlled by local Django settings and is not embedded in the browser.</small></div><div className="ri-setting-row"><span>Current session</span><strong>{props.hasToken ? props.userLabel : 'Not signed in'}</strong><small>{props.hasToken ? `${safeCount(props.aiSummary?.total_observations)} private observation(s) reported by API` : 'Public road reports remain available; private AI observations require sign-in.'}</small></div></div></Panel>
    <Panel><PanelTitle icon="activity" title="API readiness checks" action={<button className="ri-outline-button" onClick={props.onRefresh}><Icon name="refresh" size={15}/>Refresh checks</button>}/><div className="ri-service-list"><ServiceState label="Django road-report API" healthy={!props.loading && !props.publicError} unknown={props.loading} detail={props.loading ? 'Checking the current API response...' : props.publicError || 'Latest public API calls returned successfully.'}/><ServiceState label="RoutIQ observation API" healthy={props.hasToken && !props.loading && !props.aiError} unknown={props.loading || !props.hasToken} detail={!props.hasToken ? 'Sign in to check authenticated observation endpoints.' : props.loading ? 'Checking authenticated observation and stats routes...' : props.aiError || 'Authenticated observation and statistics requests returned data.'}/><ServiceState label="YOLO inference" healthy={Boolean(props.detectorReadiness?.inference_tested)} unknown={props.detectorReadinessLoading || !props.hasToken || (!props.detectorReadiness && !props.detectorReadinessError)} detail={detectorReadinessDescription(props.detectorReadiness, props.detectorReadinessError, props.detectorReadinessLoading, props.hasToken)} /></div></Panel>
    <Panel><PanelTitle icon="logout" title="Account session"/><p className="ri-muted">Sign-in tokens are kept in browser local storage by the current RoutIQ account flow. Signing out removes only those browser tokens; it does not delete server-side records.</p><div className="ri-button-row">{props.hasToken ? <button className="ri-outline-button danger" onClick={props.onSignOut}><Icon name="logout" size={15}/>Sign out</button> : <button className="ri-primary-button" onClick={props.onSignIn}>Open sign-in</button>}</div></Panel>
  </>;
}
function ServiceState({ label, healthy, unknown, detail }: { label: string; healthy: boolean; unknown?: boolean; detail: string }) {
  return <div className="ri-service-row"><span className={`ri-service-indicator${healthy ? ' healthy' : unknown ? ' unknown' : ''}`}/><div><strong>{label}</strong><small>{detail}</small></div><b>{healthy ? 'Responding' : unknown ? 'Not verified' : 'Needs check'}</b></div>;
}
