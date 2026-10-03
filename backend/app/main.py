import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.services.collector.telemetry import TelemetryWorker

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)
telemetry_worker = TelemetryWorker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("application_started", extra={"event": "application_started", "environment": settings.app_env})
    telemetry_worker.start()
    yield
    telemetry_worker.stop()
    logger.info("application_stopped", extra={"event": "application_stopped"})


app = FastAPI(
    title=settings.app_name,
    version="0.7.0",
    description="Privacy-preserving autonomous PostgreSQL performance optimization platform.",
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed", extra={"event": "request_failed", "request_id": request_id, "method": request.method, "path": request.url.path})
        raise
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    logger.info("request_completed", extra={"event": "request_completed", "request_id": request_id, "method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": duration_ms})
    return response
