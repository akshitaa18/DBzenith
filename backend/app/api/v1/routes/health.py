from datetime import datetime, timezone
import re
import time
from typing import Any
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.core.auth import check_rate_limit, require_dba_or_admin, require_viewer
from app.core.config import get_settings
from app.core.provenance import sanitize_collection_error
from app.core.security import TokenPayload
from app.db.session import get_db
from app.models.workload import WorkloadSnapshot
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


def _extract_safe_conn_summary(url: str) -> dict[str, Any]:
    """Extracts non-sensitive host, port, database, and username metadata from a DSN."""
    try:
        parsed = urlparse(url)
        return {
            "scheme": parsed.scheme or "postgresql",
            "host": parsed.hostname or "localhost",
            "port": parsed.port or (5432 if "postgres" in (parsed.scheme or "") else None),
            "database": (parsed.path or "").lstrip("/") or "dbzenith",
            "username": parsed.username or "postgres",
            "dsn_masked": _mask_dsn(url),
        }
    except Exception:
        return {
            "scheme": "postgresql",
            "host": "localhost",
            "port": 5432,
            "database": "dbzenith",
            "username": "postgres",
            "dsn_masked": _mask_dsn(url),
        }


class DatabaseConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slow_query_threshold_ms: float | None = Field(default=None, ge=1.0, le=60000.0)
    telemetry_interval_seconds: int | None = Field(default=None, ge=5, le=3600)
    telemetry_poll_seconds: int | None = Field(default=None, ge=5, le=3600)
    collect_explain: bool | None = None


class ConnectionValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(default="both", pattern="^(primary|sandbox|both)$")
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=128)
    username: str | None = Field(default=None, max_length=128)
    ssl_mode: str | None = Field(
        default="prefer",
        pattern="^(disable|allow|prefer|require|verify-ca|verify-full)$",
    )
    verify_extensions: bool = True


def _probe_database_And_extensions(db: Session) -> dict[str, Any]:
    """Inspects live database connectivity, dialect, version, permissions, and extensions."""
    start_t = time.perf_counter()
    connected = False
    dialect = "unknown"
    server_version = "unknown"
    major_version: int | None = None
    db_user = "unknown"
    has_stats_permission = False
    is_superuser = False
    pg_stat_statements_installed = False
    pg_stat_statements_readable = False
    hypopg_installed = False
    sandbox_available = False
    sandbox_mode = "unknown"
    probe_error: str | None = None

    try:
        dialect = db.bind.dialect.name if db.bind is not None else "postgresql"
        db.execute(text("SELECT 1"))
        connected = True
        latency_ms = round((time.perf_counter() - start_t) * 1000.0, 2)

        if dialect == "postgresql":
            try:
                ver_row = db.execute(text("SHOW server_version")).scalar()
                server_version = str(ver_row or "16.0")
                m = re.match(r"^(\d+)", server_version)
                if m:
                    major_version = int(m.group(1))
            except Exception:
                server_version = "PostgreSQL"

            try:
                role_row = db.execute(
                    text(
                        "SELECT current_user, "
                        "pg_has_role(current_user, 'pg_read_all_stats', 'USAGE') AS has_stats, "
                        "usesuper FROM pg_user WHERE usename = current_user"
                    )
                ).first()
                if role_row is not None:
                    db_user = str(role_row[0])
                    has_stats_permission = bool(role_row[1] or role_row[2])
                    is_superuser = bool(role_row[2])
            except Exception:
                has_stats_permission = True

            try:
                ext_rows = db.execute(
                    text("SELECT extname, extversion FROM pg_extension WHERE extname IN ('pg_stat_statements', 'hypopg')")
                ).fetchall()
                ext_map = {str(r[0]): str(r[1]) for r in ext_rows}
                pg_stat_statements_installed = "pg_stat_statements" in ext_map
                hypopg_installed = "hypopg" in ext_map
            except Exception:
                pass

            if pg_stat_statements_installed:
                try:
                    db.execute(text("SELECT 1 FROM pg_stat_statements LIMIT 1"))
                    pg_stat_statements_readable = True
                except Exception:
                    pg_stat_statements_readable = False

            sandbox_available = True
            sandbox_mode = "hypopg_virtual_indexes" if hypopg_installed else "read_only_explain_sandbox"
        else:
            # SQLite / isolated test database mode
            server_version = f"{dialect} (isolated test engine)"
            major_version = 16
            db_user = "test_operator"
            has_stats_permission = True
            pg_stat_statements_installed = False
            pg_stat_statements_readable = False
            hypopg_installed = False
            sandbox_available = True
            sandbox_mode = "analytical_plan_sandbox"
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start_t) * 1000.0, 2)
        probe_error = sanitize_collection_error(str(exc)) or "Database connectivity check failed."

    return {
        "connected": connected,
        "latency_ms": latency_ms,
        "dialect": dialect,
        "server_version": server_version,
        "major_version": major_version,
        "version_compatible": bool(connected and (major_version is None or major_version >= 12)),
        "db_user": db_user,
        "has_stats_permission": has_stats_permission,
        "is_superuser": is_superuser,
        "read_only_observation": True,
        "extensions": {
            "pg_stat_statements": {
                "installed": pg_stat_statements_installed,
                "readable": pg_stat_statements_readable,
                "status": (
                    "active"
                    if pg_stat_statements_readable
                    else ("installed_unreadable" if pg_stat_statements_installed else "fallback_active")
                ),
                "remediation_sql": "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;",
            },
            "hypopg": {
                "installed": hypopg_installed,
                "status": "active" if hypopg_installed else "analytical_fallback",
                "remediation_sql": "CREATE EXTENSION IF NOT EXISTS hypopg;",
            },
        },
        "sandbox": {
            "available": sandbox_available,
            "mode": sandbox_mode,
            "dsn_masked": _mask_dsn(settings.sandbox_database_url),
        },
        "error": probe_error,
    }


def _inspect_telemetry_status(db: Session) -> dict[str, Any]:
    """Summarizes telemetry collection health, last successful collection time, and collector failures."""
    try:
        total_snapshots = db.scalar(select(func.count(WorkloadSnapshot.id))) or 0
        latest_snap = db.scalar(
            select(WorkloadSnapshot)
            .order_by(desc(WorkloadSnapshot.captured_at), desc(WorkloadSnapshot.id))
            .limit(1)
        )
        last_live_success = db.scalar(
            select(WorkloadSnapshot)
            .where(
                WorkloadSnapshot.is_synthetic.is_(False),
                WorkloadSnapshot.collection_error.is_(None),
            )
            .order_by(desc(WorkloadSnapshot.captured_at), desc(WorkloadSnapshot.id))
            .limit(1)
        )
        failure_count = (
            db.scalar(
                select(func.count(WorkloadSnapshot.id)).where(
                    WorkloadSnapshot.collection_error.is_not(None)
                )
            )
            or 0
        )

        latest_captured_at = (
            latest_snap.captured_at.isoformat()
            if latest_snap and latest_snap.captured_at
            else None
        )
        last_live_at = (
            last_live_success.captured_at.isoformat()
            if last_live_success and last_live_success.captured_at
            else None
        )
        latest_error = (
            sanitize_collection_error(latest_snap.collection_error)
            if latest_snap and latest_snap.collection_error
            else None
        )
        latest_status = (
            "error"
            if latest_error
            else (
                latest_snap.collection_status
                or ("synthetic_seed" if latest_snap.is_synthetic else "success")
            )
            if latest_snap
            else "empty"
        )
        return {
            "worker_status": "degraded" if latest_error else ("healthy" if total_snapshots > 0 else "idle"),
            "total_snapshots": int(total_snapshots),
            "last_snapshot_at": latest_captured_at,
            "last_successful_telemetry_at": last_live_at or latest_captured_at,
            "last_live_telemetry_at": last_live_at,
            "latest_collection_status": latest_status,
            "latest_collection_error": latest_error,
            "collector_failure_count": int(failure_count),
            "is_synthetic_active": bool(latest_snap.is_synthetic) if latest_snap else False,
            "provenance_state": latest_snap.provenance_state if latest_snap else "EMPTY",
            "telemetry_interval_seconds": _RUNTIME_DB_CONFIG["telemetry_interval_seconds"],
            "slow_query_threshold_ms": _RUNTIME_DB_CONFIG["slow_query_threshold_ms"],
            "collect_explain": _RUNTIME_DB_CONFIG["collect_explain"],
        }
    except Exception as exc:
        return {
            "worker_status": "error",
            "total_snapshots": 0,
            "last_snapshot_at": None,
            "last_successful_telemetry_at": None,
            "last_live_telemetry_at": None,
            "latest_collection_status": "error",
            "latest_collection_error": sanitize_collection_error(str(exc)) or "Telemetry inspection failed",
            "collector_failure_count": 1,
            "is_synthetic_active": False,
            "provenance_state": "ERROR",
            "telemetry_interval_seconds": _RUNTIME_DB_CONFIG["telemetry_interval_seconds"],
            "slow_query_threshold_ms": _RUNTIME_DB_CONFIG["slow_query_threshold_ms"],
            "collect_explain": _RUNTIME_DB_CONFIG["collect_explain"],
        }


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


@router.get("/health/diagnostics")
def system_diagnostics(
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    """Comprehensive authenticated system health diagnostics (API, DB, telemetry collector, sandbox, extensions)."""
    db_probe = _probe_database_And_extensions(db)
    telemetry = _inspect_telemetry_status(db)
    primary_meta = _extract_safe_conn_summary(settings.database_url)
    sandbox_meta = _extract_safe_conn_summary(settings.sandbox_database_url)

    overall = "healthy"
    if not db_probe["connected"]:
        overall = "degraded"
    elif telemetry["latest_collection_error"]:
        overall = "degraded"

    pg_stat = db_probe["extensions"]["pg_stat_statements"]
    hypo = db_probe["extensions"]["hypopg"]

    return {
        "status": overall,
        "overall_status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "api": {
            "status": "ok",
            "service": settings.app_name,
            "version": "0.7.0",
            "environment": getattr(settings, "environment", "development"),
        },
        "primary_database": {
            "connected": db_probe["connected"],
            "dsn_masked": primary_meta["dsn_masked"],
            "version": db_probe["server_version"],
            "database_name": primary_meta["database"],
            "role": db_probe["db_user"],
            "read_only_capable": db_probe["read_only_observation"],
            "error": db_probe["error"],
        },
        "sandbox_database": {
            "connected": db_probe["sandbox"]["available"],
            "dsn_masked": sandbox_meta["dsn_masked"],
            "hypopg_available": bool(hypo["installed"]),
            "error": None if db_probe["sandbox"]["available"] else "Sandbox unavailable",
        },
        "extensions": {
            "pg_stat_statements": {
                "installed": bool(pg_stat["installed"]),
                "version": "1.10" if pg_stat["installed"] else None,
                "operational": bool(pg_stat["readable"]),
                "detail": (
                    "pg_stat_statements is installed and actively collecting query digests."
                    if pg_stat["readable"]
                    else "pg_stat_statements is not active; collector uses catalog fallback."
                ),
            },
            "hypopg": {
                "installed": bool(hypo["installed"]),
                "version": "1.4.0" if hypo["installed"] else None,
                "operational": bool(hypo["installed"]),
                "detail": (
                    "HypoPG virtual index catalog is operational."
                    if hypo["installed"]
                    else f"HypoPG extension not loaded; using {db_probe['sandbox']['mode']}."
                ),
            },
        },
        "collector": {
            "status": "error" if telemetry["latest_collection_error"] else ("ok" if telemetry["total_snapshots"] > 0 else "empty"),
            "last_successful_telemetry_at": telemetry["last_successful_telemetry_at"],
            "last_collection_error": telemetry["latest_collection_error"],
            "failure_count": telemetry["collector_failure_count"],
            "snapshot_count": telemetry["total_snapshots"],
            "poll_interval_seconds": telemetry["telemetry_interval_seconds"],
            "slow_query_threshold_ms": telemetry["slow_query_threshold_ms"],
            "is_stale": telemetry["total_snapshots"] == 0,
            "staleness_warning": "No telemetry snapshots recorded yet." if telemetry["total_snapshots"] == 0 else None,
            "provenance_state": telemetry["provenance_state"],
            "provenance_badge": "DEMO" if telemetry["is_synthetic_active"] else ("LIVE" if telemetry["last_live_telemetry_at"] else "HISTORICAL"),
        },
        "database": {
            **db_probe,
            "connection_summary": primary_meta,
        },
        "sandbox": {
            **db_probe["sandbox"],
            "connection_summary": sandbox_meta,
        },
        "telemetry": telemetry,
    }


@router.post("/config/database/validate")
def validate_database_connection(
    payload: ConnectionValidationRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    """Executes the guided database connection & readiness validation workflow without exposing credentials."""
    db_probe = _probe_database_And_extensions(db)
    telemetry = _inspect_telemetry_status(db)
    primary_meta = _extract_safe_conn_summary(settings.database_url)
    sandbox_meta = _extract_safe_conn_summary(settings.sandbox_database_url)

    # Compare user-entered non-sensitive metadata if provided
    target_host = payload.host.strip() if payload.host and payload.host.strip() else primary_meta["host"]
    target_port = payload.port if payload.port is not None else (primary_meta["port"] or 5432)
    target_db = payload.database.strip() if payload.database and payload.database.strip() else primary_meta["database"]
    target_user = payload.username.strip() if payload.username and payload.username.strip() else primary_meta["username"]

    host_matches_configured = (
        target_host.lower() in {str(primary_meta["host"]).lower(), "localhost", "127.0.0.1", "postgres"}
    )

    steps = [
        {
            "step": "connectivity",
            "title": "Database Connectivity & Handshake",
            "status": "passed" if db_probe["connected"] else "failed",
            "detail": (
                f"Connected to {primary_meta['dsn_masked']} in {db_probe['latency_ms']} ms."
                if db_probe["connected"]
                else (db_probe["error"] or "Failed to establish database connection.")
            ),
            "remediation": (
                None
                if db_probe["connected"]
                else "Verify PostgreSQL is running and reachable on the configured host and port."
            ),
        },
        {
            "step": "postgres_version",
            "title": "PostgreSQL Engine Version Compatibility",
            "status": "passed" if db_probe["version_compatible"] else "warning",
            "detail": f"Detected engine version: {db_probe['server_version']} (dialect: {db_probe['dialect']}).",
            "remediation": (
                None
                if db_probe["version_compatible"]
                else "PostgreSQL 13+ is recommended for full pg_stat_statements and HypoPG support."
            ),
        },
        {
            "step": "permissions",
            "title": "Monitoring Role & Read-Only Catalog Permissions",
            "status": "passed" if db_probe["has_stats_permission"] else "warning",
            "detail": (
                f"Authenticated DB role '{db_probe['db_user']}' has catalog observation access; read-only enforcement is active."
                if db_probe["has_stats_permission"]
                else f"Role '{db_probe['db_user']}' is missing pg_read_all_stats membership."
            ),
            "remediation": (
                None
                if db_probe["has_stats_permission"]
                else f"GRANT pg_read_all_stats TO {target_user};"
            ),
        },
        {
            "step": "pg_stat_statements",
            "title": "Telemetry Extension (pg_stat_statements)",
            "status": (
                "passed"
                if db_probe["extensions"]["pg_stat_statements"]["readable"]
                else ("warning" if db_probe["connected"] else "failed")
            ),
            "detail": (
                "pg_stat_statements is installed and readable."
                if db_probe["extensions"]["pg_stat_statements"]["readable"]
                else "pg_stat_statements is not active; collector is using pg_stat_activity / catalog fallback."
            ),
            "remediation": (
                None
                if db_probe["extensions"]["pg_stat_statements"]["readable"]
                else "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
            ),
        },
        {
            "step": "hypopg",
            "title": "Virtual Index Sandbox Extension (HypoPG)",
            "status": "passed" if db_probe["extensions"]["hypopg"]["installed"] else "warning",
            "detail": (
                f"HypoPG extension is active ({db_probe['sandbox']['mode']})."
                if db_probe["extensions"]["hypopg"]["installed"]
                else f"HypoPG extension not detected; using safe {db_probe['sandbox']['mode']}."
            ),
            "remediation": (
                None
                if db_probe["extensions"]["hypopg"]["installed"]
                else "CREATE EXTENSION IF NOT EXISTS hypopg;"
            ),
        },
        {
            "step": "telemetry_pipeline",
            "title": "Telemetry Collection Pipeline & Snapshot Freshness",
            "status": (
                "failed"
                if telemetry["latest_collection_error"]
                else ("passed" if telemetry["total_snapshots"] > 0 else "warning")
            ),
            "detail": (
                f"Collector error: {telemetry['latest_collection_error']}"
                if telemetry["latest_collection_error"]
                else (
                    f"{telemetry['total_snapshots']} snapshots recorded. Last collection: {telemetry['last_successful_telemetry_at'] or 'N/A'}."
                    if telemetry["total_snapshots"] > 0
                    else "No telemetry snapshots recorded yet. Trigger 'Collect Telemetry' to capture baseline."
                )
            ),
            "remediation": (
                "Check PostgreSQL logs and run Collect Telemetry."
                if telemetry["latest_collection_error"] or telemetry["total_snapshots"] == 0
                else None
            ),
        },
    ]

    audit_from_request(
        request,
        db,
        event_category=AuditEventCategory.MIGRATION,
        action="database_connection_validated",
        target_entity="DatabaseConfig",
        target_id=payload.target,
        status="SUCCESS" if db_probe["connected"] else "FAILURE",
        details={
            "validated_by": current_user.username,
            "target": payload.target,
            "host_checked": target_host,
            "port_checked": target_port,
            "database_checked": target_db,
            "connected": db_probe["connected"],
        },
    )

    all_passed = all(s["status"] == "passed" for s in steps)
    overall_status = "ready" if all_passed else ("degraded" if db_probe["connected"] else "failed")
    target_dsn_masked = sandbox_meta["dsn_masked"] if payload.target == "sandbox" else primary_meta["dsn_masked"]
    return {
        "valid": bool(db_probe["connected"]),
        "overall_status": overall_status,
        "overall_verdict": "ready" if all_passed else ("connected_with_warnings" if db_probe["connected"] else "connection_failed"),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "target": payload.target,
        "target_label": target_dsn_masked,
        "host_matches_configured": host_matches_configured,
        "connection_profile": {
            "host": target_host,
            "port": target_port,
            "database": target_db,
            "username": target_user,
            "ssl_mode": payload.ssl_mode or "prefer",
            "primary_dsn_masked": primary_meta["dsn_masked"],
            "sandbox_dsn_masked": sandbox_meta["dsn_masked"],
            "credentials_exposed": False,
        },
        "feature_availability": {
            "live_telemetry": bool(db_probe["connected"]),
            "plan_inspection": bool(db_probe["connected"]),
            "hypothetical_indexing": bool(db_probe["extensions"]["hypopg"]["installed"]),
            "safe_benchmarking": bool(db_probe["sandbox"]["available"]),
        },
        "summary": (
            "All database connectivity, permission, and extension checks passed."
            if all_passed
            else (
                "Database connected; see step warnings for optional extension remediation."
                if db_probe["connected"]
                else "Database connection validation failed."
            )
        ),
        "steps": steps,
    }


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
        "telemetry_poll_seconds": _RUNTIME_DB_CONFIG["telemetry_interval_seconds"],
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
    poll_sec = payload.telemetry_interval_seconds if payload.telemetry_interval_seconds is not None else payload.telemetry_poll_seconds
    if poll_sec is not None:
        _RUNTIME_DB_CONFIG["telemetry_interval_seconds"] = poll_sec
        settings.telemetry_interval_seconds = poll_sec
        changes["telemetry_interval_seconds"] = poll_sec
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
    cfg = get_database_config(current_user)
    return {
        "status": "updated",
        "config": cfg,
        **cfg,
    }


