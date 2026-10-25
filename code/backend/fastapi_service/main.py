"""
RoutIQ — internal FastAPI vision service.

The service is never exposed as a public API. For local Windows development,
bind Uvicorn to 127.0.0.1:8100. Existing Linux deployments may continue to use
their private Unix-domain-socket service configuration.

Local start:
    python -m uvicorn fastapi_service.main:app --host 127.0.0.1 --port 8100
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from fastapi_service.routers import analytics, postprocess, validate, vision
from fastapi_service.schemas import ServiceHealthResponse

logger = logging.getLogger("fastapi_service")


# ── Lifespan: startup / shutdown hooks ──────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("RoutIQ FastAPI service starting; bind address is controlled by Uvicorn")
    yield
    logger.info("RoutIQ FastAPI service shutting down")


# ── App factory ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="RoutIQ Vision Service",
    description=(
        "Private internal RoutIQ vision service for image inference, result validation, "
        "post-processing, and analytics aggregation. Local development binds to loopback only."
    ),
    version="1.0.0",
    docs_url=None,       # Disable Swagger UI (internal service — no public docs)
    redoc_url=None,      # Disable ReDoc
    openapi_url=None,    # Disable OpenAPI schema endpoint
    lifespan=lifespan,
)


# ── Routers ──────────────────────────────────────────────────────────────────

app.include_router(validate.router, tags=["validation"])
app.include_router(postprocess.router, tags=["postprocessing"])
app.include_router(analytics.router, tags=["analytics"])
app.include_router(vision.router, tags=["vision"])


# ── Health check ─────────────────────────────────────────────────────────────

@app.get("/health", response_model=ServiceHealthResponse)
async def health() -> dict:
    """
    Liveness probe used by Django and local development diagnostics.
    """
    return {"status": "ok", "service": "routiq-vision"}


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler so FastAPI never returns an unstructured 500.
    Django's client checks for non-2xx and triggers fallback logic.
    """
    logger.exception("Unhandled error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal FastAPI error", "path": str(request.url.path)},
    )
