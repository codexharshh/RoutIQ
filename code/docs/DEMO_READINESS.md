# RoutIQ Demonstration Readiness

**Status reviewed:** 2026-10-19

## Sprint 11 local HTTP smoke check

The frontend, Django, and FastAPI services were started temporarily on the documented local ports. The Django process received a process-local blank `DATABASE_URL`, selecting SQLite; no migrations were run. The frontend returned HTTP 200 at `/project/routiq/`, Django's admin login returned HTTP 200, and the map API returned HTTP 401 without authentication both directly and through the Vite proxy. FastAPI health returned HTTP 200 with `status=ok`; detector readiness returned HTTP 200 with `weights_not_found`. These checks verify service reachability and expected authentication behavior, not successful real inference or a complete browser session. All three temporary service processes were stopped after the checks. SHA-256 hashes of `backend/routiq.sqlite3` and `backend/routiq_government.sqlite3` matched their pre-check values.

## Verified through automated tests

- The Django suite passed 157 tests on SQLite test databases. It includes upload validation, deterministic mocked detection, Django persistence, owner-scoped map feed, GPS updates, private evidence access and expiry, detector readiness, temporal review, and storage diagnostics.
- A focused backend run passed 43 road-observation API, location, vision-client, and detector-readiness tests.
- FastAPI's unittest suite passed 43 tests for service health, request validation, detector status, and the isolated mocked `/detect` endpoint.
- `npm.cmd run lint` passed. The TypeScript production build completed to a fresh temporary directory outside the project. Vite reported a chunk-size advisory for the JavaScript bundle.
- Django system checks passed. The storage preflight found configured development ports and private local evidence storage; it warned about pending road-observation migrations in the selected local database and missing optional dashcam dependencies.
- The local Django test run used process-local whitespace for `DATABASE_URL`, causing settings to select `backend/routiq.sqlite3`. Django created and destroyed its test database. The private `.env` file was not edited or displayed.
- Existing integration tests verify the image-upload-to-map API path using a deterministic test detector. This is simulated test coverage, not evidence of real YOLO inference.

## Present but not fully verified end to end

- Django stores road observations and serves authenticated, owner-scoped map data. The React Leaflet overlay requests that feed and renders only returned observations. Automated tests cover the Django API contract; no live browser-to-Django-to-FastAPI-to-map session was run in this sprint.
- Django calls FastAPI for inference and validates its response. FastAPI remains stateless in the application workflow. Service-client behavior and both services' test clients were tested separately; no live two-process inference request was performed.
- Image evidence uses Django `FileSystemStorage` at a private filesystem root outside public media/static paths. Authenticated owner access, expiry, deletion, and traversal protection are covered by tests. Supabase stores the database path and expiry metadata, not the image bytes. A cloud deployment needs durable private storage with restrictive permissions and owner-scoped delivery; an ephemeral or multi-instance filesystem is not sufficient.
- Supabase contains the application schema, but its migration history has four duplicated `token_blacklist` migration records and Sprint 9's migration command failed during permission creation. See [SPRINT9_MIGRATION_INCIDENT.md](SPRINT9_MIGRATION_INCIDENT.md). Do not use Supabase for a live demo until the owner reviews and approves the proposed read-only-verified correction.
- No compatible `.pt`, `.onnx`, or `.engine` weights were found in the bounded RoutIQ model directories. The configured detector preflight reports `weights_not_found`; no real YOLO inference has been run. The app must be described as unavailable for real detection until an authorized compatible model is configured and actually tested.
- Dashcam integration tests cover the adapter, but live processing remains unavailable while optional runtime packages are missing (`cvzone`, `geopy`, and `easyocr`). No dependencies were installed.
- There is no labeled repeat-pass evaluation dataset; research performance and repair verification remain unvalidated.

## Local startup

Use three terminals. These commands do not run database migrations.

### 1. Django API

From `D:\RoutIQ\code\backend`:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

The private `backend\.env` currently selects Supabase when it supplies `DATABASE_URL`. To use local SQLite without editing that file, set a process-local whitespace value before starting Django:

```powershell
$env:DATABASE_URL = ' '
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Settings strip whitespace and use `backend/routiq.sqlite3`. Keep the value process-local; do not put credentials or connection strings in documentation or logs. The government alias remains `backend/routiq_government.sqlite3`.

### 2. FastAPI vision service

From `D:\RoutIQ\code\backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn fastapi_service.main:app --host 127.0.0.1 --port 8100
```

The health endpoint reports service liveness only. Detector status currently reports missing configured weights. Do not represent the service as providing real detections.

### 3. React + TypeScript frontend

From `D:\RoutIQ\code`:

```powershell
npm.cmd run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/project/routiq/`. The Vite proxy targets Django at `http://127.0.0.1:8000` by default.

## Environment configuration

- `DATABASE_URL`: optional PostgreSQL Session Pooler URL. When absent/blank after whitespace trimming, Django uses local SQLite for `default`. Never print or commit the URL.
- `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CORS_ALLOWED_ORIGINS`, and `DJANGO_CSRF_TRUSTED_ORIGINS`: production secret and explicit host/origin allowlists. Keep secret values in private environment configuration.
- `ROUTIQ_VISION_URL`: FastAPI base URL; local default is `http://127.0.0.1:8100`.
- `ROUTIQ_DJANGO_URL`: Vite proxy target; local default is `http://127.0.0.1:8000`.
- `ROUTIQ_DETECTOR_BACKEND`, `ROUTIQ_MODEL_WEIGHTS`, `ROUTIQ_MODEL_NAME`, and `ROUTIQ_MODEL_VERSION`: vision-service detector configuration. Configure only authorized local weights after class labels and provenance are checked. Never commit model weights.
- `ROUTIQ_PRIVATE_EVIDENCE_ROOT` and `ROUTIQ_EVIDENCE_RETENTION_DAYS`: private evidence filesystem root and retention period. The root must be outside public static/media paths and on durable, access-controlled storage for deployment.

## Remaining blockers to a credible demonstration

1. Resolve the Supabase migration incident through the documented owner-approved procedure before relying on the cloud database.
2. Supply an authorized YOLO model whose actual class names map to RoutIQ's four supported classes, then verify one real inference with a permitted test image.
3. Provide durable private evidence storage for the deployment environment and verify owner-scoped retrieval there.
4. Install the already-approved dashcam runtime dependencies only after a separate authorization and test the complete video/GPS processing path.
5. Run one attended browser session across upload, real inference, persistence, GPS/map display, and private evidence review once the service and storage blockers are resolved.
6. Collect independently labeled, route-separated repeat-pass data before reporting research performance or repair-verification results.

No feature in this checklist should be described as complete solely because a mocked test passed.
