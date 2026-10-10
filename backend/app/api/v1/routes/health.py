import re
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import check_rate_limit, require_dba_or_admin
from app.core.config import get_settings
from app.core.security import TokenPayload
from app.db.session import get_db
from app.schemas.health import HealthResponse, ReadinessResponse
from app.services.audit.recorder import AuditEventCategory, audit_from_request

router = APIRouter(tags=["health"])
settings = get_settings()

# Runtime-adjustable non-sensitive connection/telemetry parameters
_RUNTIME_DB_CONFIG: dict[str, Any] = {
    "slow_query_threshold_ms": settings.slow_query_threshold_ms,
    "telemetry_interval_seconds": settings.telemetry_interval_seconds,
    "collect_explain": settings.collect_explain,
}


def _mask_dsn(url: str) -> str:
    """Masks embedded credentials in a database DSN so secrets are never exposed."""
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url)


class DatabaseConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slow_query_threshold_ms: float | None = Field(default=None, ge=1.0, le=60000.0)
    telemetry_interval_seconds: int | None = Field(default=None, ge=5, le=3600)
    collect_explain: bool | None = None


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Intentionally public liveness probe for container orchestrators."""
    check_rate_limit(request)
    return HealthResponse(status="ok", service=settings.app_name, version="0.7.0")


@router.get("/ready", response_model=ReadinessResponse)
def ready(request: Request, db: Session = Depends(get_db)) -> ReadinessResponse:
    """Intentionally public readiness probe verifying database connectivity."""
    check_rate_limit(request)
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database_unavailable") from exc
    return ReadinessResponse(status="ready", database="ok")


@router.get("/config/database")
def get_database_config(
    _user: TokenPayload = Depends(require_dba_or_admin),
) -> dict[str, Any]:
    """Returns database connection configuration with all secrets and passwords masked (DBA/ADMIN only)."""
    return {
        "database_url_masked": _mask_dsn(settings.database_url),
        "sandbox_database_url_masked": _mask_dsn(settings.sandbox_database_url),
        "slow_query_threshold_ms": _RUNTIME_DB_CONFIG["slow_query_threshold_ms"],
        "telemetry_interval_seconds": _RUNTIME_DB_CONFIG["telemetry_interval_seconds"],
        "collect_explain": _RUNTIME_DB_CONFIG["collect_explain"],
        "read_only_observation": True,
    }


@router.patch("/config/database")
def update_database_config(
    payload: DatabaseConfigUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_dba_or_admin),
) -> dict[str, Any]:
    """Updates runtime database telemetry thresholds (DBA/ADMIN only) and records an audit event."""
    changes: dict[str, Any] = {}
    if payload.slow_query_threshold_ms is not None:
        _RUNTIME_DB_CONFIG["slow_query_threshold_ms"] = payload.slow_query_threshold_ms
        settings.slow_query_threshold_ms = payload.slow_query_threshold_ms
        changes["slow_query_threshold_ms"] = payload.slow_query_threshold_ms
    if payload.telemetry_interval_seconds is not None:
        _RUNTIME_DB_CONFIG["telemetry_interval_seconds"] = payload.telemetry_interval_seconds
        settings.telemetry_interval_seconds = payload.telemetry_interval_seconds
        changes["telemetry_interval_seconds"] = payload.telemetry_interval_seconds
    if payload.collect_explain is not None:
        _RUNTIME_DB_CONFIG["collect_explain"] = payload.collect_explain
        settings.collect_explain = payload.collect_explain
        changes["collect_explain"] = payload.collect_explain

    audit_from_request(
        request,
        db,
        event_category=AuditEventCategory.MIGRATION,
        action="database_config_updated",
        target_entity="DatabaseConfig",
        target_id="runtime",
        status="SUCCESS",
        details={"updated_by": current_user.username, "changes": changes},
    )
    return {
        "status": "updated",
        "config": get_database_config(current_user),
    }

