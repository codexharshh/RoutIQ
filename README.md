# RoutIQ

### Intelligent Road Infrastructure Analytics

> **Smarter roads. Better decisions.**

RoutIQ is a full-stack road-inspection platform for detecting road damage, storing geolocated observations, and visualizing road-health data. It combines a React map-based interface with a Django system of record and a stateless FastAPI vision service.

Live demo: [rout-iq-two.vercel.app](https://rout-iq-two.vercel.app)

## What it does

- Upload road images and run damage detection.
- Track potholes, longitudinal cracks, transverse cracks, and alligator cracks.
- Display authenticated, owner-scoped observations on interactive Leaflet maps.
- Attach coordinates manually, from browser location, or from image GPS metadata.
- Review road observations over time with transparent, quality-aware matching.
- Process dashcam video and GPS traces through the legacy integration.
- Retain private source evidence for a configurable period.
- Expose road-health and government reporting APIs.

## Architecture

```text
React + TypeScript + Vite
            │
            ▼
       Django REST API ───────► Database and application records
            │
            ▼
   FastAPI vision service ────► YOLO / hosted detector
```

- **Frontend:** React, TypeScript, Vite, React Leaflet
- **Backend:** Django, Django REST Framework, JWT authentication
- **Vision service:** FastAPI and Uvicorn; stateless inference and detector readiness checks
- **Storage:** SQLite for local development or PostgreSQL for production; private evidence storage is configured separately
- **Deployment:** Vercel frontend, Render-compatible backend, or the bundled Docker images

## Repository layout

```text
.
├── code/
│   ├── src/                 # React application
│   ├── tests/               # Frontend service tests
│   ├── backend/             # Django and FastAPI services
│   ├── docs/                # Readiness, migration, and storage notes
│   └── package.json
├── Dockerfile               # Full-stack image with local YOLO inference
├── Dockerfile.render        # Lightweight hosted-detector image
└── .github/workflows/       # CI checks
```

## Quick start

### Prerequisites

- Node.js 20+
- Python 3.11+
- A Python virtual environment for the backend
- Optional: PostgreSQL, YOLO weights, and the dashcam dependencies

### 1. Configure the backend

```bash
cd code/backend
python -m venv .venv

# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -e .
cp .env.example .env
```

Set a private `DJANGO_SECRET_KEY` in `.env`. Leave `DATABASE_URL` blank for local SQLite, or provide a PostgreSQL connection string. Never commit `.env`, credentials, or model weights.

### 2. Start Django

```bash
cd code/backend
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

### 3. Start the vision service

In another terminal:

```bash
cd code/backend
python -m uvicorn fastapi_service.main:app --host 127.0.0.1 --port 8100
```

The service runs at `http://127.0.0.1:8100`. Its `/health` endpoint indicates liveness only; it does not prove that a detector or model is ready.

### 4. Start the frontend

In a third terminal:

```bash
cd code
npm ci --legacy-peer-deps
npm run dev -- --host 127.0.0.1
```

Open [http://127.0.0.1:5173/project/routiq/](http://127.0.0.1:5173/project/routiq/). Vite proxies API requests to Django at `http://127.0.0.1:8000` by default; override this with `ROUTIQ_DJANGO_URL`.

## Common commands

Run from `code/` unless noted:

```bash
npm run dev       # Start Vite
npm run build     # Type-check and build the frontend
npm run lint      # Run ESLint
npm test          # Run frontend service tests
```

Backend checks (from `code/backend/`):

```bash
python manage.py check
python manage.py test
python -m unittest discover -s fastapi_service/tests -p "test_*.py"
python manage.py routiq_preflight
```

`routiq_preflight` is read-only by default and reports configuration, storage, migration, and service readiness.

## Detector configuration

Detection is disabled by default in `.env.example`. To use a local, authorized model, configure the vision-service process with:

```bash
ROUTIQ_DETECTOR_BACKEND=ultralytics
ROUTIQ_MODEL_WEIGHTS=/absolute/path/to/road-damage-model.pt
ROUTIQ_MODEL_NAME=routiq-road-damage
ROUTIQ_MODEL_VERSION=your-model-version
```

Supported damage classes:

- Pothole
- Longitudinal crack
- Transverse crack
- Alligator crack

Hosted deployments can use the Roboflow backend configured by `Dockerfile.render`. Keep API keys server-side and never expose them through `VITE_` variables.

## API highlights

| Route | Purpose |
| --- | --- |
| `POST /api/v1/auth/register/` | Register an account |
| `POST /api/v1/auth/login/` | Obtain JWT credentials |
| `POST /api/v1/road-observations/detect/` | Run detection and persist observations |
| `GET /api/v1/road-observations/map/` | Return the authenticated user's mapped observations |
| `GET /api/v1/road-observations/detector-status/` | Check detector readiness |
| `POST /api/v1/road-observations/temporal-review/` | Compare saved observations over time |
| `GET\|DELETE /api/v1/road-observations/sessions/<id>/evidence/` | Retrieve or remove private evidence |

Legacy pothole, dashcam, and government routes remain under `/api/` and `/gov-api/`.

## Deployment

### Vercel + hosted backend

Deploy the frontend from `code/` using the included `vercel.json`:

```bash
cd code
npm ci --legacy-peer-deps
npm run build
```

Rewrite rules route API requests to the configured Render backend. Review and update deployment URLs and environment variables before using them in production.

### Docker

The root `Dockerfile` builds the frontend and runs Nginx, Django, FastAPI, and Supervisor in one container. It downloads and verifies an attributed YOLO checkpoint during the image build.

```bash
docker build -t routiq .
docker run --env-file code/backend/.env -p 10000:10000 routiq
```

`Dockerfile.render` provides a smaller image intended for a hosted detector and an external frontend. Production deployments require a durable PostgreSQL database, explicit host/origin allowlists, private evidence storage, and securely managed secrets.

## Current limitations

- A detector health or readiness response does not establish successful real-world inference.
- Model accuracy and repair-verification quality require an authorized, labeled evaluation dataset and a documented protocol.
- Private evidence storage must use durable, access-controlled storage in multi-instance deployments.
- The legacy dashcam workflow has additional optional runtime dependencies and should be validated separately.
- Review scores are transparent heuristics, not calibrated probabilities, and a match does not prove that damage was repaired.

See [`code/README_RoutIQ.md`](code/README_RoutIQ.md) and [`code/docs/DEMO_READINESS.md`](code/docs/DEMO_READINESS.md) for detailed operational guidance and verification boundaries.

## Security and privacy

- Keep `.env`, database URLs, API keys, JWT secrets, and model files out of source control.
- Set explicit production values for `DJANGO_ALLOWED_HOSTS`, `DJANGO_CORS_ALLOWED_ORIGINS`, and `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Store private evidence outside public static/media paths and configure an appropriate retention period.
- Do not treat browser device location as proof of where an uploaded image was captured.

## License and attribution

Review the repository's third-party notices and upstream model terms before redistributing RoutIQ or any bundled model assets. Model weights and hosted detector services may have separate licenses and usage requirements.

## Maintainer

RoutIQ is maintained by [Harsh](https://github.com/codexharshh).
