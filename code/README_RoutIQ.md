# RoutIQ: Intelligent Road Infrastructure Analytics

**RoutIQ — Smarter Roads. Better Decisions.**

RoutIQ is maintained by **Harsh** and combines a React + TypeScript frontend, Django system of record, stateless FastAPI vision service, YOLOv8 road-damage detection, and React Leaflet maps. The application includes mapped road observations and an experimental quality-aware temporal review workflow. See `THIRD_PARTY_NOTICES.md` for upstream components and license context.

## Architecture

- `src/`: React + TypeScript application, upload workflows, and Leaflet maps.
- `backend/`: Django REST API, authentication, and persistent records.
- `backend/fastapi_service/`: internal, stateless inference and validation service.
- `backend/road_damage/`: detector configuration, Ultralytics adapter, preprocessing, and class mapping.
- `backend/road_observations/`: inspection sessions, damage instances, observations, assessments, and matches.
- Django owns application data. FastAPI receives image bytes and returns detections; it does not write application records.

## Local development on Windows

Start Django from the backend directory. The Vite proxy defaults to the same port, 8000.

```powershell
Set-Location D:\RoutIQ\code\backend
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

In a second terminal, start the frontend:

```powershell
Set-Location D:\RoutIQ\code
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/project/routiq/`.

### Optional PostgreSQL development database

Local development uses `backend/routiq.sqlite3` when `DATABASE_URL` is unset or blank. To use Supabase, copy the PostgreSQL **Session Pooler** connection URI from the Supabase connection dialog into the private `backend/.env` as `DATABASE_URL`. Keep the URI out of source control and do not paste it into logs or support output. The application enforces SSL, uses a 10-second connection timeout, and enables Django connection health checks. The installed environment must include `dj-database-url` and either `psycopg2-binary` or `psycopg`.

After setting the variable, run Django's system check from `backend` with the same environment. A later connection test should use a reviewed, non-destructive check such as Django's database `check` command. Do not run migrations or transfer existing SQLite records as part of connection verification. The separate `government` database alias remains SQLite-backed.

To use another Django development port, set the Vite process environment before starting it:

```powershell
$env:ROUTIQ_DJANGO_URL = 'http://127.0.0.1:8000'
npm run dev -- --host 127.0.0.1
```

## Vision service and YOLOv8

The Django observation API calls FastAPI at `ROUTIQ_VISION_URL`, which defaults to `http://127.0.0.1:8100`. Start the service in a separate terminal. The default detector configuration is disabled, so this starts service health checks without implying that inference is ready:

```powershell
Set-Location D:\RoutIQ\code\backend
.\.venv\Scripts\python.exe -m uvicorn fastapi_service.main:app --host 127.0.0.1 --port 8100
```

Use only a locally available, authorized YOLOv8 weights file. Do not commit model weights or credentials. Enable inference only in the vision-service process environment after provenance and class labels have been reviewed:

```powershell
$env:ROUTIQ_DETECTOR_BACKEND = 'ultralytics'
$env:ROUTIQ_MODEL_WEIGHTS = 'D:\path\to\authorized\road-damage-model.pt'
$env:ROUTIQ_MODEL_NAME = 'routiq-road-damage'
$env:ROUTIQ_MODEL_VERSION = 'your-model-version'
```

The `GET /health` endpoint reports FastAPI liveness only. `GET /detector-status` is a separate preflight that may load configured weights to check class compatibility. `ready_to_test` confirms loading and supported labels only, not successful inference. Model labels must map to RoutIQ's supported classes: pothole, longitudinal crack, transverse crack, and alligator crack. The authenticated Django detector-status endpoint distinguishes an unreachable service, timeout, malformed readiness report, disabled or unconfigured detection, incompatible labels, loaded but unverified weights, and an inference check explicitly reported as tested.

For a local smoke check, start Django and FastAPI in separate terminals, then run `python manage.py routiq_preflight` from `backend`. Start Vite in a third terminal and confirm the SPA loads at `http://127.0.0.1:5173/project/routiq/`. The Vite proxy uses `ROUTIQ_DJANGO_URL` (default `http://127.0.0.1:8000`); a request to the protected Django detector-status route without a token should return HTTP 401 through the proxy. For an isolated smoke test, set `ROUTIQ_VITE_CACHE_DIR` to a fresh directory under the system temporary folder so Vite does not use or refresh the project dependency cache. A passing `/health` response does not establish model readiness.

## Image inspection, GPS, and map behavior

Sign in, select an image in the AI Detection Studio, and submit it. Django validates the upload and optional coordinates, calls FastAPI, then saves the returned detections in one database transaction. Inference errors do not create observation records.

Coordinates are optional. Users can add manual coordinates or attach the browser's current device location; device location is not evidence of where a previously captured photo was taken. When `photo_exif` is selected, the server extracts coordinates from the uploaded image's GPS EXIF tags and rejects client-supplied coordinates as a substitute. The source and available GPS accuracy are retained with the observation. Only authenticated, owner-scoped observations with valid coordinates are returned by the damage map feed.

The separate dashcam workflow accepts authenticated uploads and processes only uploaded files identified by generated IDs. Supported video containers are MP4, MOV, and AVI; GPS trace files must contain GPRMC and GPGGA records. Temporary uploads are stored in user-scoped directories. Cleanup is restricted to administrators and their own temporary uploads. When processing produces complete per-detection rows with matched GPS, the command validates them and writes owner-scoped, idempotent modern observations; aggregate frame counts are not converted into detections. The legacy runtime requires `cvzone`, `geopy`, `easyocr`, and a compatible configured model. Per-detection dashcam metadata does not currently retain a private source frame for evidence review. See `backend/road_observations/LEGACY_DASHCAM_INTEGRATION.md` for the input contract and current verification limits.

## Review and repair interpretation

Temporal review compares two saved positive observations using class, distance, time separation, and recorded observation-quality inputs. Its score is a transparent heuristic, not a calibrated probability. A candidate match or a missing later detection does not prove that damage was repaired. Assessments remain attributed to their reviewer and are not marked independently verified by the system.

New successful image inspections with detections retain one private source image for 30 days by default (`ROUTIQ_EVIDENCE_RETENTION_DAYS`). Files are stored outside `MEDIA_ROOT` under `ROUTIQ_PRIVATE_EVIDENCE_ROOT` (default: `backend/private_evidence/`) and are accessible only through the authenticated, owner-scoped evidence endpoint. Owners can delete evidence with `DELETE /api/v1/road-observations/sessions/<id>/evidence/`; records remain. The `purge_expired_evidence` management command reports expired files by default; pass `--execute` to delete them. Existing sessions and inspections without detections do not receive evidence files. Configure storage capacity and retention to match the deployment's privacy policy.

Retained images enable future visual review, but do not independently establish that a repair occurred. Reliable repair evaluation still requires matched before-and-after evidence, independent review, labeled ground truth, and a documented evaluation protocol.

## API overview

- `POST /api/v1/auth/register/` and `POST /api/v1/auth/login/`: account registration and JWT login.
- `GET /api/v1/road-observations/`: list the authenticated user's observations.
- `POST /api/v1/road-observations/detect/`: run inference and persist observations.
- `GET /api/v1/road-observations/detector-status/`: authenticated, sanitized FastAPI detector preflight; a loaded model is not proof of successful inference.
- `GET /api/v1/road-observations/map/`: return the authenticated user's GPS-tagged map observations.
- `PATCH /api/v1/road-observations/<id>/location/`: add or update an owned observation's coordinates.
- `POST /api/v1/road-observations/temporal-review/`: compare two owned observations as a review candidate.
- `GET|DELETE /api/v1/road-observations/sessions/<id>/evidence/`: retrieve or delete the owner's retained inspection image.
- Existing pothole and dashcam routes remain under `/api/`; government routes remain under `/gov-api/`.

## Production configuration

Use `routiq_config.production_settings` only with deployment-specific environment configuration. Set a strong `DJANGO_SECRET_KEY` of at least 50 characters, comma-separated `DJANGO_ALLOWED_HOSTS`, and explicit comma-separated `DJANGO_CORS_ALLOWED_ORIGINS` and `DJANGO_CSRF_TRUSTED_ORIGINS` containing the deployed frontend origins. Production settings reject missing host/origin allowlists and disable credentialed cross-origin requests. Keep `DJANGO_SECURE_SSL_REDIRECT=true` when the application is served over HTTPS. Configure trusted proxy HTTPS forwarding only when the deployment proxy sets the corresponding header securely.

The additive `road_observations.0002_inspection_evidence` migration must be reviewed and applied as a deployment step before image evidence is enabled; it has not been run as part of development verification. Do not run migrations against production without a reviewed backup and deployment plan. The default local database configuration uses `backend/routiq.sqlite3`; legacy government models use `backend/routiq_government.sqlite3` through the existing database router. Preserve existing databases and uploaded data during development.

Run the read-only local operational preflight from `backend` with `python manage.py routiq_preflight`. It reports Django configuration, host and origin policy, evidence storage, migration state, development service URLs, and FastAPI/model readiness without printing secret values or applying migrations. Add `--skip-service-checks` to skip the internal FastAPI request. Review `road_observations/MIGRATION_READINESS.md` before activating the evidence migration.

## Verification limits

Mock-based unit tests cover selected API and temporal behavior, but they do not establish real YOLO accuracy, end-to-end map correctness on field images, or repair-verification performance. Report research metrics only after evaluating a documented, labeled dataset and protocol. The Vite proxy target can be changed with `ROUTIQ_DJANGO_URL`; the default is `http://127.0.0.1:8000`.


## Maintainer

- **Project:** RoutIQ — Intelligent Road Infrastructure Analytics
- **Maintainer:** Harsh
- **Profile:** https://github.com/codexharshh
- **Tagline:** Smarter Roads. Better Decisions.

RoutIQ branding identifies the current project maintainer; it does not supersede third-party copyright, license, or attribution requirements. Review `THIRD_PARTY_NOTICES.md` before redistributing the project.
