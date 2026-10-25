import { useCallback, useEffect, useState } from 'react';
import type { CSSProperties, FormEvent } from 'react';
import { detectorReadinessMessage } from '../services/detectorReadiness';
import type { DetectorReadiness } from '../services/detectorReadiness';
import { normalizeApiPayload } from '../services/apiPayload';
import type { ApiPayload } from '../services/apiPayload';
import {
  getCurrentDeviceLocation,
  extractExifGps,
  validateCoordinates,
} from '../services/gpsLocationService';

type RecordItem = {
  id: number;
  damage_class: string;
  confidence: number;
  latitude: number | string | null;
  longitude: number | string | null;
  assessment_status: string;
  observed_at: string;
  created_at: string;
  bbox?: number[] | null;
  metadata?: Record<string, unknown> | null;
  source_name?: string;
  model_name?: string;
  model_version?: string;
  frame_number?: number | null;
  gps_accuracy_m?: number | null;
};

type TemporalReviewResult = {
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
  repair_verification: string;
};

function downloadTextFile(filename: string, contents: string, contentType: string): void {
  const blob = new Blob([contents], { type: contentType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

type AuthPayload = {
  access?: string;
  refresh?: string;
  user?: { username?: string; email?: string; [key: string]: unknown };
  data?: AuthPayload;
  message?: string;
  detail?: string;
  errors?: Record<string, unknown>;
  success?: boolean;
};

const API_ROOT = '/api/v1';
const ACCESS_KEY = 'routiq_access_token';
const REFRESH_KEY = 'routiq_refresh_token';
const USER_KEY = 'routiq_user';

async function readResponse(response: Response): Promise<ApiPayload> {
  const text = await response.text();
  try {
    return normalizeApiPayload(JSON.parse(text), text);
  } catch { return normalizeApiPayload(null, text); }
}

function explainError(payload: ApiPayload, fallback: string): string {
  const clean = (value: unknown): string =>
    typeof value === 'string' || typeof value === 'number' ? String(value).trim() : '';
  const flatten = (value: unknown): string[] => {
    if (typeof value === 'string' || typeof value === 'number') {
      const text = String(value).trim();
      return text ? [text] : [];
    }
    if (Array.isArray(value)) return value.flatMap(flatten);
    if (value && typeof value === 'object') {
      return Object.entries(value as Record<string, unknown>).flatMap(([key, item]) =>
        flatten(item).map((part) => `${key}: ${part}`)
      );
    }
    return [];
  };

  const detail = clean(payload?.detail);
  if (detail) return detail;

  const nestedData = payload.data;
  const nestedRecord = nestedData !== null && typeof nestedData === 'object' && !Array.isArray(nestedData)
    ? nestedData as Record<string, unknown>
    : undefined;
  const validation = payload.errors ?? nestedRecord?.errors ?? payload.non_field_errors;
  const validationMessages = flatten(validation);
  if (validationMessages.length) return validationMessages.join(' | ');

  const topLevelFields = payload && typeof payload === 'object'
    ? Object.entries(payload)
        .filter(([key]) => !['success', 'message', 'detail', 'data', 'errors'].includes(key))
        .flatMap(([key, value]) => flatten(value).map((part) => `${key}: ${part}`))
    : [];
  if (topLevelFields.length) return topLevelFields.join(' | ');

  const message = clean(payload?.message);
  if (message && message.toLowerCase() !== 'registration failed') return message;
  return fallback;
}

function currentToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

function apiHeaders(json = false): Record<string, string> {
  const result: Record<string, string> = { Accept: 'application/json' };
  if (json) result['Content-Type'] = 'application/json';
  const token = currentToken();
  if (token) result.Authorization = `Bearer ${token}`;
  return result;
}

function normalizeAuth(payload: AuthPayload): AuthPayload {
  return payload?.data && typeof payload.data === 'object' ? payload.data : payload;
}

function storeAuth(payload: AuthPayload): string {
  const data = normalizeAuth(payload);
  if (!data.access) throw new Error('The RoutIQ login API did not return an access token.');
  localStorage.setItem(ACCESS_KEY, data.access);
  if (data.refresh) localStorage.setItem(REFRESH_KEY, data.refresh);
  if (data.user) localStorage.setItem(USER_KEY, JSON.stringify(data.user));
  return data.access;
}

function title(value: string): string {
  return String(value || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function RoutIQAccountGate({ onAuthenticated, initialMessage = '' }: { onAuthenticated: () => void; initialMessage?: string }) {
  const [mode, setMode] = useState<'login' | 'signup'>('signup');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialMessage);
  const [notice, setNotice] = useState('');

  async function sendJson(path: string, body: Record<string, string>) {
    const endpoint = `${API_ROOT}/auth/${path}`;
    let response: Response;
    try {
      response = await fetch(endpoint, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store',
      });
    } catch (cause) {
      console.error('[RoutIQ auth] Request could not reach the API:', endpoint, cause);
      throw new Error(`Cannot reach RoutIQ authentication API (${endpoint}). Check that Django is running on port 8000 and Vite's /api proxy is active.`);
    }
    console.info(`[RoutIQ auth] POST ${endpoint} -> HTTP ${response.status}`);
    const payload = await readResponse(response);
    if (!response.ok || payload?.success === false) {
      throw new Error(explainError(payload, `RoutIQ API returned HTTP ${response.status} for ${path}.`));
    }
    return payload as AuthPayload;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setNotice(mode === 'signup' ? 'Sending account creation request to RoutIQ…' : 'Sending sign-in request to RoutIQ…');
    try {
      if (mode === 'signup') {
        if (password.length < 8) throw new Error('Use a password with at least 8 characters.');
        if (password !== confirmPassword) throw new Error('Passwords do not match.');
        await sendJson('register/', { username: username.trim(), email: email.trim(), password });
        setNotice('RoutIQ account created. Signing you in…');
      }
      const loginName = mode === 'signup' ? username.trim() : username.trim();
      const loginPayload = await sendJson('login/', { username: loginName, password });
      storeAuth(loginPayload);
      onAuthenticated();
     } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not complete the account request.';
      const isDuplicateAccount = mode === 'signup' && /already exists|already registered|already in use|already taken|unique constraint/i.test(message);

      if (isDuplicateAccount) {
        const usernameConflict = /username\s*:\s*[^|;]*(already exists|already in use|already taken)|username and email|username or email/i.test(message);
        const emailConflict = /email\s*:\s*[^|;]*(already exists|already in use|already taken)|username and email|username or email/i.test(message);
        const loginName = emailConflict && !usernameConflict ? email.trim() : username.trim();

        setMode('login');
        setUsername(loginName || username.trim());
        setError('');
        setNotice('An account with these details already exists. Trying sign-in with the password you entered...');

        try {
          const existingLogin = await sendJson('login/', { username: loginName || username.trim(), password });
          storeAuth(existingLogin);
          onAuthenticated();
          return;
        } catch (loginErr) {
          const loginMessage = loginErr instanceof Error ? loginErr.message : 'Sign-in did not succeed.';
          setNotice('I switched the form to Sign in. Use the existing account credentials, or choose a different username and email.');
          setError(`An account already exists, but automatic sign-in did not work: ${loginMessage}`);
        }
      } else {
        setNotice('');
        setError(message);
      }
    } finally {
      setBusy(false);
    }
  }

  const fieldStyle: CSSProperties = {
    width: '100%', padding: '11px 12px', border: '1px solid #cbd5e1',
    borderRadius: 8, font: 'inherit', boxSizing: 'border-box',
  };

  return (
    <main className="routiq-auth-shell">
      <section className="routiq-auth-card">
        <div className="routiq-auth-mark">R</div>
        <p className="routiq-eyebrow">ROUTIQ ACCOUNT</p>
        <h2>{mode === 'signup' ? 'Create your RoutIQ account' : 'Welcome back to RoutIQ'}</h2>
        <p className="routiq-auth-description">Join a smarter way to monitor, analyze and improve road infrastructure with AI.</p>
        <div className="routiq-auth-switch" role="tablist" aria-label="Account action">
          <button type="button" role="tab" aria-selected={mode === 'signup'} className={mode === 'signup' ? 'selected' : ''} onClick={() => { setMode('signup'); setError(''); setNotice(''); }}>Create account</button>
          <button type="button" role="tab" aria-selected={mode === 'login'} className={mode === 'login' ? 'selected' : ''} onClick={() => { setMode('login'); setError(''); setNotice(''); }}>Sign in</button>
        </div>
{/* RoutIQ auth footer v2 */}


        {error && <p className="routiq-form-error" role="alert">{error}</p>}
        {notice && <p className="routiq-form-notice" role="status">{notice}</p>}
        <form onSubmit={(event) => void submit(event)} className="routiq-auth-form" aria-busy={busy}>
          <label>{mode === 'signup' ? 'Username' : 'Username or email'}
            <input style={fieldStyle} autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} placeholder={mode === 'signup' ? 'Choose a username' : 'Enter username or email'} />
          </label>
          {mode === 'signup' && <label>Email address
            <input style={fieldStyle} type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
          </label>}
          <label>Password
            <input style={fieldStyle} type="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} required value={password} onChange={(event) => setPassword(event.target.value)} placeholder={mode === 'signup' ? 'At least 8 characters' : 'Your password'} />
          </label>
          {mode === 'signup' && <label>Confirm password
            <input style={fieldStyle} type="password" autoComplete="new-password" required value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} placeholder="Enter password again" />
          </label>}
          <button type="submit" disabled={busy} className="routiq-primary-button">{busy ? 'Please wait…' : mode === 'signup' ? 'Create account and continue' : 'Sign in to RoutIQ'}</button>
<div className="routiq-auth-or-divider" aria-hidden="true">
          <span>OR</span>
        </div>
        <p className="routiq-auth-alternate">
          {mode === 'signup' ? 'Already have an account?' : "Don't have an account?"}
          <button
            type="button"
            onClick={() => {
              setMode(mode === 'signup' ? 'login' : 'signup');
              setError('');
              setNotice('');
            }}
          >
            {mode === 'signup' ? 'Sign in' : 'Create account'}
          </button>
        </p>
        <div className="routiq-auth-security-note">
          <span className="routiq-auth-security-icon" aria-hidden="true">✓</span>
          <span>Your data is secure and used only for road infrastructure research and analysis.</span>
        </div>

        </form>
      </section>
    </main>
  );
}

export default function RoadDamageConsole() {
  const [authenticated, setAuthenticated] = useState(() => Boolean(currentToken()));
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [gps, setGps] = useState<{ latitude: number; longitude: number } | null>(null);
  const [gpsSource, setGpsSource] = useState<'device_current' | 'manual' | 'photo_exif' | 'unspecified'>('unspecified');
  const [gpsAccuracyM, setGpsAccuracyM] = useState<number | null>(null);
  const [gpsLocating, setGpsLocating] = useState(false);
  const [manualLatitude, setManualLatitude] = useState('');
  const [manualLongitude, setManualLongitude] = useState('');
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [editingLocationId, setEditingLocationId] = useState<number | null>(null);
  const [editLatitude, setEditLatitude] = useState('');
  const [editLongitude, setEditLongitude] = useState('');
  const [records, setRecords] = useState<RecordItem[]>([]);
  const [latest, setLatest] = useState<RecordItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [temporalFirst, setTemporalFirst] = useState('');
  const [temporalSecond, setTemporalSecond] = useState('');
  const [temporalBusy, setTemporalBusy] = useState(false);
  const [temporalResult, setTemporalResult] = useState<TemporalReviewResult | null>(null);
  const [detectorReadiness, setDetectorReadiness] = useState<DetectorReadiness | null>(null);
  const [detectorReadinessError, setDetectorReadinessError] = useState('');
  const [liveInferenceVerified, setLiveInferenceVerified] = useState(false);

  useEffect(() => {
    if (!file) { setPreview(''); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const expireSession = useCallback(() => {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
    setAuthenticated(false);
  }, []);

  const refresh = useCallback(async () => {
    if (!currentToken()) { setRecords([]); return; }
    try {
      const response = await fetch(`${API_ROOT}/road-observations/`, { headers: apiHeaders() });
      const payload = await readResponse(response);
      if (response.status === 401) {
        expireSession();
        setError('Your RoutIQ session expired. Sign in again to access saved observations.');
        return;
      }
      if (!response.ok) throw new Error(explainError(payload, `Could not load observations (${response.status}).`));
      setRecords(Array.isArray(payload) ? payload : Array.isArray(payload?.results) ? payload.results : []);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load saved observations.');
    }
  }, [expireSession]);

  useEffect(() => {
    if (authenticated) void refresh();
    else setRecords([]);
  }, [authenticated, refresh]);

  useEffect(() => {
    if (!authenticated) { setDetectorReadiness(null); return; }
    let active = true;
    void fetch(`${API_ROOT}/road-observations/detector-status/`, { headers: apiHeaders(), cache: 'no-store' })
      .then(async (response) => {
        const payload = await readResponse(response);
        if (response.status === 401) { expireSession(); throw new Error('Your RoutIQ session expired. Sign in again.'); }
        if (!response.ok || typeof payload.status !== 'string' || typeof payload.inference_tested !== 'boolean') {
          throw new Error('Detector readiness is unavailable. Check that the Django and vision services are running.');
        }
        return payload as unknown as DetectorReadiness;
      })
      .then((payload) => { if (active) { setDetectorReadiness(payload); setDetectorReadinessError(''); } })
      .catch((cause: unknown) => {
        if (active) setDetectorReadinessError(cause instanceof Error ? cause.message : 'Detector readiness is unavailable.');
      });
    return () => { active = false; };
  }, [authenticated, expireSession]);

  async function handleUseCurrentLocation() {
    setGpsLocating(true);
    setError('');
    try {
      const location = await getCurrentDeviceLocation();
      setManualLatitude(location.latitude.toFixed(7));
      setManualLongitude(location.longitude.toFixed(7));
      setGps({ latitude: location.latitude, longitude: location.longitude });
      setGpsSource('device_current');
      setGpsAccuracyM(location.accuracy);
      setNotice(
        `Current device location acquired: ${location.latitude.toFixed(6)}, ${location.longitude.toFixed(6)} (accuracy: ±${location.accuracy} m). Verify this matches the road damage location before submitting.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to acquire current location.');
    } finally {
      setGpsLocating(false);
    }
  }

  async function detect() {
    if (!file) { setError('Choose a road image first.'); return; }
    setBusy(true); setError(''); setNotice(''); setLatest([]);
    try {
      const form = new FormData();
      form.append('image', file);
      if (gps) {
        if (gpsSource === 'photo_exif') {
          // As required by Django road_observations/views.py:
          // Photo GPS coordinates are read from image metadata; do not submit coordinates with photo_exif.
          form.append('coordinate_source', 'photo_exif');
        } else {
          form.append('latitude', String(gps.latitude));
          form.append('longitude', String(gps.longitude));
          form.append('coordinate_source', gpsSource);
          if (gpsAccuracyM !== null) form.append('gps_accuracy_m', String(gpsAccuracyM));
        }
      }
      const response = await fetch(`${API_ROOT}/road-observations/detect/`, {
        method: 'POST', headers: apiHeaders(), body: form,
      });
      const payload = await readResponse(response);
      if (response.status === 401) {
        expireSession();
        throw new Error('Your RoutIQ session expired. Sign in again.');
      }
      if (!response.ok) throw new Error(explainError(payload, `Detection failed (${response.status}).`));
      const results = Array.isArray(payload?.results) ? payload.results : [];
      setLatest(results);
      setLiveInferenceVerified(true);
      setNotice(`Detection completed. ${payload?.count ?? results.length} result(s) saved to RoutIQ.`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Detection failed.');
    } finally {
      setBusy(false);
    }
  }

  function beginLocationEdit(item: RecordItem) {
    setEditingLocationId(item.id);
    setEditLatitude(item.latitude == null ? '' : String(item.latitude));
    setEditLongitude(item.longitude == null ? '' : String(item.longitude));
    setError('');
    setNotice('Enter the coordinates where this photo was captured.');
  }

  async function saveLocation(id: number) {
    const validation = validateCoordinates(editLatitude, editLongitude);
    if (!validation.valid || validation.latitude === undefined || validation.longitude === undefined) {
      setError(validation.error || 'Coordinates out of range. Latitude must be -90 to 90 and longitude -180 to 180.');
      setNotice('');
      return;
    }
    const { latitude, longitude } = validation;
    setBusy(true); setError(''); setNotice('Saving photo coordinates…');
    try {
      const response = await fetch(`${API_ROOT}/road-observations/${id}/location/`, {
        method: 'PATCH', headers: apiHeaders(true),
        body: JSON.stringify({ latitude, longitude }),
      });
      const payload = await readResponse(response);
      if (response.status === 401) {
        expireSession();
        throw new Error('Your RoutIQ session expired. Sign in again.');
      }
      if (!response.ok) throw new Error(explainError(payload, `Saving location failed (${response.status}).`));
      setEditingLocationId(null);
      setNotice(`GPS coordinates saved for observation #${id}. Return to the map to see its marker.`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save observation coordinates.');
      setNotice('');
    } finally { setBusy(false); }
  }

  async function markUncertain(id: number) {
    try {
      const response = await fetch(`${API_ROOT}/road-observations/${id}/assess/`, {
        method: 'POST',
        headers: apiHeaders(true),
        body: JSON.stringify({
          status: 'uncertain',
          confidence: 0.5,
          rationale: 'Flagged for manual review; this is not a repair verification.',
        }),
      });
      const payload = await readResponse(response);
      if (response.status === 401) {
        expireSession();
        throw new Error('Your RoutIQ session expired. Sign in again.');
      }
      if (!response.ok) throw new Error(explainError(payload, `Review update failed (${response.status}).`));
      setNotice(`Observation #${id} marked uncertain for manual review.`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update the observation.');
    }
  }

  function exportCsv() {
    const columns = ['id', 'damage_class', 'confidence', 'latitude', 'longitude', 'assessment_status', 'observed_at', 'source_name', 'model_name', 'model_version', 'frame_number', 'bbox'];
    const lines = [columns.map(csvCell).join(','), ...records.map((item) => columns.map((column) => csvCell((item as unknown as Record<string, unknown>)[column])).join(','))];
    downloadTextFile(`routiq-observations-${new Date().toISOString().slice(0, 10)}.csv`, '\uFEFF' + lines.join('\r\n'), 'text/csv;charset=utf-8');
    setNotice(`Exported ${records.length} observation(s) to CSV.`);
    setError('');
  }

  function exportGeoJson() {
    const mapped = records.filter((item) => item.latitude !== null && item.latitude !== undefined && item.longitude !== null && item.longitude !== undefined);
    if (!mapped.length) {
      setError('No observations have GPS coordinates yet. Enter the photo coordinates before exporting GeoJSON.');
      setNotice('');
      return;
    }
    const featureCollection = {
      type: 'FeatureCollection',
      features: mapped.map((item) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [Number(item.longitude), Number(item.latitude)] },
        properties: {
          id: item.id, damage_class: item.damage_class, confidence: item.confidence,
          status: item.assessment_status, observed_at: item.observed_at,
          source_name: item.source_name ?? '', model_name: item.model_name ?? '', model_version: item.model_version ?? '',
        },
      })),
    };
    downloadTextFile(`routiq-mapped-observations-${new Date().toISOString().slice(0, 10)}.geojson`, JSON.stringify(featureCollection, null, 2), 'application/geo+json;charset=utf-8');
    setNotice(`Exported ${mapped.length} GPS-mapped observation(s) to GeoJSON.`);
    setError('');
  }


  async function compareTemporalEvidence() {
    const firstId = Number(temporalFirst);
    const secondId = Number(temporalSecond);
    if (!firstId || !secondId) { setError('Choose two GPS-mapped observations first.'); setNotice(''); return; }
    if (firstId === secondId) { setError('Choose two different observations.'); setNotice(''); return; }
    setTemporalBusy(true); setError(''); setNotice('Comparing repeat-pass evidence with the quality-aware review rule…'); setTemporalResult(null);
    try {
      const response = await fetch(`${API_ROOT}/road-observations/temporal-review/`, {
        method: 'POST', headers: apiHeaders(true),
        body: JSON.stringify({ observation_a_id: firstId, observation_b_id: secondId, distance_threshold_m: 15 }),
      });
      const payload = await readResponse(response);
      if (response.status === 401) { expireSession(); throw new Error('Your RoutIQ session expired. Sign in again.'); }
      if (!response.ok) throw new Error(explainError(payload, `Temporal review failed (${response.status}).`));
      const result = payload as unknown as TemporalReviewResult;
      setTemporalResult(result);
      setNotice(`Temporal comparison #${result.match_id} saved: ${title(result.decision)}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Temporal evidence review failed.');
      setNotice('');
    } finally { setTemporalBusy(false); }
  }

  const card: CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 14, padding: 18, boxShadow: '0 6px 20px rgba(15,23,42,.04)' };
  const button: CSSProperties = { padding: '9px 12px', cursor: 'pointer', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff', color: '#17212b' };
  const mappedRecords = records.filter((item) => item.latitude !== null && item.latitude !== undefined && item.longitude !== null && item.longitude !== undefined);
  const temporalDecisionLabel = temporalResult ? (temporalResult.decision === 'same_damage' ? 'Possible repeat sighting' : temporalResult.decision === 'different_damage' ? 'Different-damage candidate' : 'Insufficient evidence - review required') : '';

  if (!authenticated) {
    return <RoutIQAccountGate onAuthenticated={() => { setAuthenticated(true); setError(''); setNotice('Signed in to RoutIQ.'); }} initialMessage={error} />;
  }

  return (
    <main className="routiq-detection-page">
      <div className="routiq-workspace-heading">
        <div><p className="routiq-eyebrow">RoutIQ / INSPECTION WORKSPACE</p><h1>AI Road Damage Detection</h1><p>Analyze road images, save observations, and review location-aware results.</p></div>
        <button style={button} onClick={() => { expireSession(); setNotice(''); setError(''); }}>Sign out</button>
      </div>
      {error && <p role="alert" className="routiq-form-error">{error}</p>}
      {notice && <p role="status" className="routiq-form-notice">{notice}</p>}
      <section style={{ ...card, marginBottom: 18 }} aria-labelledby="detector-readiness-title" role="status">
        <h2 id="detector-readiness-title">Road-damage detector readiness</h2>
        {detectorReadinessError ? <p>{detectorReadinessError}</p> : detectorReadiness ? (
          <>
            <p><strong>Status:</strong> {liveInferenceVerified ? 'Inference Succeeded (this session)' : title(detectorReadiness.status.replace(/_/g, ' '))}</p>
            <p><strong>Model labels:</strong> {title(detectorReadiness.labels.replace(/_/g, ' '))}</p>
            <p>{liveInferenceVerified ? 'The image-analysis endpoint returned a successful response during this session. Startup readiness is reported separately.' : detectorReadinessMessage(detectorReadiness)}</p>
            {!detectorReadiness.inference_tested && !liveInferenceVerified && ['disabled', 'missing_weights_path', 'weights_not_found', 'invalid_weights_path', 'incompatible_labels', 'dependency_missing', 'ready_to_test', 'weights_present_unverified'].includes(detectorReadiness.status) && <p className="routiq-muted"></p>}
          </>
        ) : <p>Checking detector configuration…</p>}
      </section>
      <div className="routiq-detection-grid">
        <section style={card}>
          <h2>Inspect a road image</h2>
          <p className="routiq-muted">Accepted formats: JPG, PNG, WebP. Maximum size: 20 MB.</p>
          <input type="file" accept=".jpg,.jpeg,.png,.webp" onChange={(event) => {
            const selected = event.target.files?.[0] ?? null;
            setError(''); setNotice(''); setLatest([]); setImageSize({ width: 0, height: 0 });
            setGps(null); setGpsSource('unspecified'); setGpsAccuracyM(null); setManualLatitude(''); setManualLongitude('');
            if (selected && !/\.(jpe?g|png|webp)$/i.test(selected.name)) { setFile(null); setError('Use JPG, PNG or WebP.'); }
            else if (selected && selected.size > 20 * 1024 * 1024) { setFile(null); setError('Maximum image size is 20 MB.'); }
            else {
              setFile(selected);
              if (selected) {
                void extractExifGps(selected).then((exifGps) => {
                  if (exifGps) {
                    setManualLatitude(exifGps.latitude.toFixed(7));
                    setManualLongitude(exifGps.longitude.toFixed(7));
                    setGps({ latitude: exifGps.latitude, longitude: exifGps.longitude });
                    setGpsSource('photo_exif');
                    setGpsAccuracyM(exifGps.accuracyM ?? null);
                    setNotice(`Photo GPS metadata detected: ${exifGps.latitude.toFixed(6)}, ${exifGps.longitude.toFixed(6)}${exifGps.accuracyM !== undefined ? ` (accuracy: ±${exifGps.accuracyM} m)` : ''}. Coordinates pre-filled from image EXIF. You can confirm or adjust them before submitting.`);
                  } else {
                    setNotice('No GPS metadata found in image. You can click "Use My Current Location" if captured on-site, or enter coordinates manually.');
                  }
                });
              }
            }
          }} />
          {preview && (
            <div className="routiq-image-stage">
              <img
                src={preview}
                alt="Selected road preview with detection evidence"
                className="routiq-image-preview"
                onLoad={(event) => setImageSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
              />
              {imageSize.width > 0 && imageSize.height > 0 && latest.some((item) => Array.isArray(item.bbox) && item.bbox.length === 4) && (
                <svg className="routiq-image-boxes" viewBox={`0 0 ${imageSize.width} ${imageSize.height}`} preserveAspectRatio="none" role="img" aria-label="YOLO detection bounding boxes">
                  {latest.filter((item) => Array.isArray(item.bbox) && item.bbox.length === 4).map((item) => {
                    const [x1, y1, x2, y2] = item.bbox as number[];
                    if (![x1, y1, x2, y2].every(Number.isFinite) || x2 <= x1 || y2 <= y1) return null;
                    const labelY = Math.max(18, y1 - 7);
                    const label = `${title(item.damage_class)} ${(item.confidence * 100).toFixed(0)}%`;
                    return <g key={item.id}>
                      <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="rgba(13,148,136,0.14)" stroke="#0d9488" strokeWidth={Math.max(2, imageSize.width / 500)} />
                      <text x={x1 + 4} y={labelY} fill="#ffffff" stroke="#064e3b" strokeWidth={Math.max(2, imageSize.width / 400)} paintOrder="stroke" fontSize={Math.max(14, imageSize.width / 42)} fontWeight="700">{label}</text>
                    </g>;
                  })}
                </svg>
              )}
            </div>
          )}
          <div className="routiq-coordinate-grid">
            <label>Photo latitude
              <input
                type="number"
                step="any"
                min="-90"
                max="90"
                value={manualLatitude}
                onChange={(event) => {
                  setManualLatitude(event.target.value);
                  if (gpsSource !== 'manual') {
                    setGpsSource('manual');
                    setGpsAccuracyM(null);
                  }
                }}
                placeholder="e.g. 28.6139"
              />
            </label>
            <label>Photo longitude
              <input
                type="number"
                step="any"
                min="-180"
                max="180"
                value={manualLongitude}
                onChange={(event) => {
                  setManualLongitude(event.target.value);
                  if (gpsSource !== 'manual') {
                    setGpsSource('manual');
                    setGpsAccuracyM(null);
                  }
                }}
                placeholder="e.g. 77.2090"
              />
            </label>
            <button
              style={button}
              type="button"
              disabled={gpsLocating}
              onClick={() => void handleUseCurrentLocation()}
              title="Capture current browser device GPS coordinates"
            >
              {gpsLocating ? 'Acquiring location…' : 'Use My Current Location'}
            </button>
            <button
              type="button"
              style={button}
              onClick={() => {
                const latText = manualLatitude.trim();
                const lonText = manualLongitude.trim();
                if (!latText && !lonText) {
                  setGps(null);
                  setGpsSource('unspecified');
                  setGpsAccuracyM(null);
                  setError('');
                  setNotice('No coordinates attached. This inspection will be saved without a map location.');
                  return;
                }
                const validation = validateCoordinates(latText, lonText);
                if (!validation.valid || validation.latitude === undefined || validation.longitude === undefined) {
                  setError(validation.error || 'Coordinates out of range. Latitude must be -90 to 90 and longitude -180 to 180.');
                  setNotice('');
                  return;
                }
                setGps({ latitude: validation.latitude, longitude: validation.longitude });
                setGpsSource('manual');
                setGpsAccuracyM(null);
                setError('');
                setNotice('Photo coordinates attached. The saved observation can now be shown on the map.');
              }}
            >
              Apply photo coordinates
            </button>
          </div>
          <p className="routiq-muted">
            Enter or confirm the location where the road damage actually occurred. Current device GPS represents where you are standing now; verify or correct coordinates before submitting if the photo was captured elsewhere.
          </p>
          {gps && (
            <div style={{ margin: '8px 0', padding: '8px 12px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, fontSize: 13 }}>
              <strong style={{ color: '#166534' }}>
                Attached GPS: {gps.latitude.toFixed(6)}, {gps.longitude.toFixed(6)}
                {gpsAccuracyM !== null && ` (accuracy: ±${gpsAccuracyM} m)`}
              </strong>
              <div style={{ color: '#15803d', marginTop: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>Source: {gpsSource === 'device_current' ? 'Current Device Location (Browser GPS)' : gpsSource === 'photo_exif' ? 'Photo EXIF Metadata' : 'Manual Coordinates'}</span>
                <button
                  type="button"
                  style={{ ...button, padding: '3px 8px', fontSize: 12, marginLeft: 8 }}
                  onClick={() => {
                    setGps(null);
                    setGpsSource('unspecified');
                    setGpsAccuracyM(null);
                    setManualLatitude('');
                    setManualLongitude('');
                    setNotice('Coordinates cleared. Inspection will be saved without map coordinates.');
                  }}
                >
                  Clear
                </button>
              </div>
            </div>
          )}
          <button className="routiq-primary-button" disabled={!file || busy} onClick={() => void detect()}>{busy ? 'Analyzing image…' : 'Detect road damage'}</button>
        </section>
        <section style={card}>
          <h2>Latest detection results <span className="routiq-count">{latest.length}</span></h2>
          {!latest.length && <p className="routiq-muted">Detection results will appear here after an image is analyzed.</p>}
          {latest.map((item) => <article className="routiq-result-row" key={item.id}>
            <strong>{title(item.damage_class)}</strong><br />
            Observation #{item.id} · Confidence {(item.confidence * 100).toFixed(1)}%<br />
            <span className="routiq-muted">Status: {title(item.assessment_status)}</span>
          </article>)}
        </section>
      </div>
      <section style={{ ...card, marginTop: 18, overflowX: 'auto' }}>
        <div className="routiq-table-heading"><div><h2>Saved observations</h2><p className="routiq-muted">{records.length} saved observation(s), {records.filter((item) => item.latitude != null && item.longitude != null).length} with GPS coordinates</p></div><div className="routiq-export-actions"><button style={button} onClick={() => void refresh()}>Refresh records</button><button style={button} onClick={exportCsv} disabled={!records.length}>Export CSV</button><button style={button} onClick={exportGeoJson} disabled={!records.some((item) => item.latitude != null && item.longitude != null)}>Export GeoJSON</button></div></div>
        <table className="routiq-observation-table">
          <thead><tr>{['ID', 'Damage type', 'Confidence', 'GPS', 'Review status', 'Observed at', 'Action'].map((column) => <th key={column}>{column}</th>)}</tr></thead>
          <tbody>{records.map((item) => <tr key={item.id}>
            <td>{item.id}</td><td>{title(item.damage_class)}</td><td>{(item.confidence * 100).toFixed(1)}%</td>
            <td>
              {editingLocationId === item.id ? (
                <div className="routiq-saved-gps-editor">
                  <input aria-label={`Latitude for observation ${item.id}`} type="number" step="any" min="-90" max="90" value={editLatitude} onChange={(event) => setEditLatitude(event.target.value)} placeholder="Latitude" />
                  <input aria-label={`Longitude for observation ${item.id}`} type="number" step="any" min="-180" max="180" value={editLongitude} onChange={(event) => setEditLongitude(event.target.value)} placeholder="Longitude" />
                  <button style={button} type="button" disabled={busy} onClick={() => void saveLocation(item.id)}>Save GPS</button>
                  <button style={button} type="button" disabled={busy} onClick={() => setEditingLocationId(null)}>Cancel</button>
                </div>
              ) : (
                <div className="routiq-saved-gps-cell">
                  <span>{item.latitude != null && item.longitude != null ? `${item.latitude}, ${item.longitude}` : 'Not provided'}</span>
                  <button style={button} type="button" onClick={() => beginLocationEdit(item)}>{item.latitude != null && item.longitude != null ? 'Edit GPS' : 'Add GPS'}</button>
                </div>
              )}
            </td>
            <td>{title(item.assessment_status)}</td><td>{new Date(item.observed_at || item.created_at).toLocaleString()}</td>
            <td><button style={button} onClick={() => void markUncertain(item.id)}>Flag for review</button></td>
          </tr>)}</tbody>
        </table>
        <p className="routiq-muted routiq-note">A missing GPS position cannot be mapped reliably. Missing detections do not prove that road damage has been repaired.</p>
      </section>
      <section style={{ ...card, marginTop: 18 }} aria-labelledby="routiq-temporal-review-title" hidden data-routiq-hidden-upload-temporal-review="true">
        <h2 id="routiq-temporal-review-title">Repeated-pass evidence review</h2>
        <p className="routiq-muted">Compare two GPS-mapped observations from separate passes. RoutIQ scores location, time separation, detector confidence, and available image quality; weak evidence produces an abstention instead of a confident match.</p>
        {mappedRecords.length < 2 ? (
          <p className="routiq-form-notice">This account has {mappedRecords.length} GPS-mapped observation(s). Add GPS to a saved record and capture another pass before comparing repeated observations.</p>
        ) : (
          <div className="routiq-temporal-review-grid">
            <label>Earlier / reference observation
              <select value={temporalFirst} onChange={(event) => { setTemporalFirst(event.target.value); setTemporalResult(null); }} style={{ width: '100%', padding: 10, borderRadius: 8, border: '1px solid #cbd5e1', font: 'inherit' }}>
                <option value="">Choose observation</option>
                {mappedRecords.map((item) => <option key={item.id} value={item.id}>#{item.id} - {title(item.damage_class)} - {new Date(item.observed_at || item.created_at).toLocaleString()}</option>)}
              </select>
            </label>
            <label>Later / comparison observation
              <select value={temporalSecond} onChange={(event) => { setTemporalSecond(event.target.value); setTemporalResult(null); }} style={{ width: '100%', padding: 10, borderRadius: 8, border: '1px solid #cbd5e1', font: 'inherit' }}>
                <option value="">Choose observation</option>
                {mappedRecords.map((item) => <option key={item.id} value={item.id}>#{item.id} - {title(item.damage_class)} - {new Date(item.observed_at || item.created_at).toLocaleString()}</option>)}
              </select>
            </label>
            <button type="button" style={{ ...button, alignSelf: 'end' }} disabled={temporalBusy || !temporalFirst || !temporalSecond || temporalFirst === temporalSecond} onClick={() => void compareTemporalEvidence()}>
              {temporalBusy ? 'Comparing evidence…' : 'Compare observations'}
            </button>
          </div>
        )}
        {temporalResult && (
          <div className="routiq-temporal-result" role="status" aria-live="polite">
            <h3>{temporalDecisionLabel}</h3>
            <p><strong>Decision:</strong> {title(temporalResult.decision)}{temporalResult.abstained ? ' (abstained)' : ''}</p>
            <p><strong>Match score:</strong> {temporalResult.score == null ? 'Not scoreable' : `${(temporalResult.score * 100).toFixed(1)}%`}</p>
            <p><strong>GPS separation:</strong> {temporalResult.distance_m == null ? 'Unavailable' : `${temporalResult.distance_m.toFixed(1)} m`} · <strong>Time gap:</strong> {temporalResult.temporal_gap_hours == null ? 'Unavailable' : `${temporalResult.temporal_gap_hours.toFixed(1)} h`}</p>
            <p><strong>Observation quality:</strong> A {(temporalResult.quality_a.score * 100).toFixed(0)}% · B {(temporalResult.quality_b.score * 100).toFixed(0)}%</p>
            {temporalResult.reasons.length > 0 && <ul>{temporalResult.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>}
            <p className="routiq-muted"><strong>Important:</strong> This is a repeat-sighting candidate, not repair verification. Missing detections or weak image/GPS evidence never prove a road has been repaired.</p>
          </div>
        )}
      </section>
    </main>
  );
}
