"""Data provenance states, metadata sanitization, and schema helpers for DBZenith."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


class ProvenanceState(str, Enum):
    """Explicit provenance classifications for all DBZenith observations, estimates, and benchmarks."""

    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"
    LIVE_TELEMETRY = "LIVE_TELEMETRY"
    HISTORICAL_OBSERVATION = "HISTORICAL_OBSERVATION"
    HYPOTHETICAL_PLAN_ESTIMATE = "HYPOTHETICAL_PLAN_ESTIMATE"
    SANDBOX_BENCHMARK = "SANDBOX_BENCHMARK"
    VERIFIED_POST_CHANGE = "VERIFIED_POST_CHANGE"


class ProvenanceBadgeLabel(str, Enum):
    """Consistent UI badge labels corresponding to ProvenanceState."""

    DEMO = "DEMO"
    LIVE = "LIVE"
    HISTORICAL = "HISTORICAL"
    ESTIMATED = "ESTIMATED"
    SIMULATED = "SIMULATED"
    VERIFIED = "VERIFIED"


STATE_TO_BADGE: dict[str, str] = {
    ProvenanceState.SYNTHETIC_DEMO.value: ProvenanceBadgeLabel.DEMO.value,
    ProvenanceState.LIVE_TELEMETRY.value: ProvenanceBadgeLabel.LIVE.value,
    ProvenanceState.HISTORICAL_OBSERVATION.value: ProvenanceBadgeLabel.HISTORICAL.value,
    ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value: ProvenanceBadgeLabel.ESTIMATED.value,
    ProvenanceState.SANDBOX_BENCHMARK.value: ProvenanceBadgeLabel.SIMULATED.value,
    ProvenanceState.VERIFIED_POST_CHANGE.value: ProvenanceBadgeLabel.VERIFIED.value,
}


_CREDENTIAL_PATTERN = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")
_STRING_LITERAL_PATTERN = re.compile(r"'(?:''|[^'])*'")
_NUMBER_LITERAL_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
_WS_PATTERN = re.compile(r"\s+")


def sanitize_source_identifier(url_or_name: str | None) -> str:
    """Extracts a safe, credential-free source identifier from a database URL or name.

    Never persists passwords, usernames, query tokens, or raw connection strings.
    """
    if not url_or_name:
        return "unknown-source"
    raw = str(url_or_name).strip()
    if raw.startswith("synthetic://"):
        return raw[:128]
    if "://" not in raw:
        cleaned = _CREDENTIAL_PATTERN.sub(r"\1***\3", raw)
        return cleaned[:128]

    try:
        parsed = urlparse(raw)
        scheme = (parsed.scheme or "db").split("+")[0]
        if scheme == "sqlite":
            return "sqlite://isolated-test-db"
        host = parsed.hostname or "localhost"
        port = f":{parsed.port}" if parsed.port else ""
        path = (parsed.path or "").lstrip("/") or "postgres"
        return f"{scheme}://{host}{port}/{path}"[:128]
    except Exception:
        return "postgresql://redacted-host/db"


def sanitize_collection_error(error: Any) -> str | None:
    """Sanitizes a collection error so no passwords, connection strings, or stack traces are stored."""
    if not error:
        return None
    first_line = str(error).strip().splitlines()[0] if str(error).strip() else ""
    if not first_line:
        return None
    redacted = _CREDENTIAL_PATTERN.sub(r"\1***\3", first_line)
    redacted = re.sub(r"(?i)(password|secret|token)\s*=\s*\S+", r"\1=***", redacted)
    return redacted[:500]


def compute_query_fingerprint(sql: str | None) -> str:
    """Computes a structural SHA-256 fingerprint of a SQL statement with literals scrubbed."""
    if not sql:
        return "qfp_empty"
    scrubbed = _STRING_LITERAL_PATTERN.sub("$?", sql)
    scrubbed = _NUMBER_LITERAL_PATTERN.sub("$?", scrubbed)
    scrubbed = _WS_PATTERN.sub(" ", scrubbed).strip().lower()
    digest = hashlib.sha256(scrubbed.encode("utf-8")).hexdigest()[:16]
    return f"qfp_{digest}"


def badge_for_state(state: str | ProvenanceState | None) -> str:
    if isinstance(state, ProvenanceState):
        return STATE_TO_BADGE.get(state.value, ProvenanceBadgeLabel.HISTORICAL.value)
    return STATE_TO_BADGE.get(str(state or ""), ProvenanceBadgeLabel.HISTORICAL.value)


def resolve_observation_provenance(
    *,
    provenance_state: str | None,
    is_synthetic: bool | None,
    captured_at: datetime | None,
    staleness_threshold_seconds: int = 300,
    is_latest: bool = True,
    collection_status: str | None = None,
    collection_error: str | None = None,
) -> dict[str, Any]:
    """Resolves the effective provenance state, badge, and staleness of an observation.

    Enforces:
    - Synthetic records always resolve to SYNTHETIC_DEMO (DEMO).
    - Missing collection timestamps never appear as current/LIVE.
    - Historical or stale observations resolve to HISTORICAL_OBSERVATION (HISTORICAL) with a warning.
    - Verified post-change production observations resolve to VERIFIED_POST_CHANGE (VERIFIED).
    """
    raw_state = (provenance_state or "").upper()
    synthetic = bool(is_synthetic) or raw_state == ProvenanceState.SYNTHETIC_DEMO.value

    now = datetime.now(timezone.utc)
    age_seconds: float | None = None
    if captured_at is not None:
        cap_utc = captured_at if captured_at.tzinfo is not None else captured_at.replace(tzinfo=timezone.utc)
        age_seconds = round(max(0.0, (now - cap_utc).total_seconds()), 1)

    if synthetic:
        return {
            "provenance_state": ProvenanceState.SYNTHETIC_DEMO.value,
            "provenance_badge": ProvenanceBadgeLabel.DEMO.value,
            "is_synthetic": True,
            "is_measured": False,
            "is_stale": False,
            "staleness_seconds": age_seconds,
            "staleness_warning": None,
            "collection_status": collection_status or "synthetic_seed",
            "collection_error": sanitize_collection_error(collection_error),
            "demo_mode_active": True,
        }

    if raw_state == ProvenanceState.VERIFIED_POST_CHANGE.value:
        is_stale = age_seconds is None or age_seconds > staleness_threshold_seconds
        return {
            "provenance_state": ProvenanceState.VERIFIED_POST_CHANGE.value,
            "provenance_badge": ProvenanceBadgeLabel.VERIFIED.value,
            "is_synthetic": False,
            "is_measured": True,
            "is_stale": is_stale,
            "staleness_seconds": age_seconds,
            "staleness_warning": (
                f"Verified observation is {int(age_seconds)}s old."
                if age_seconds and is_stale
                else None
            ),
            "collection_status": collection_status or "success",
            "collection_error": sanitize_collection_error(collection_error),
            "demo_mode_active": False,
        }

    # Missing timestamp -> never display as current or LIVE
    if captured_at is None or age_seconds is None:
        return {
            "provenance_state": ProvenanceState.HISTORICAL_OBSERVATION.value,
            "provenance_badge": ProvenanceBadgeLabel.HISTORICAL.value,
            "is_synthetic": False,
            "is_measured": False,
            "is_stale": True,
            "staleness_seconds": None,
            "staleness_warning": "Collection timestamp is missing; observation is treated as historical/unverified.",
            "collection_status": collection_status or "missing_timestamp",
            "collection_error": sanitize_collection_error(collection_error),
            "demo_mode_active": False,
        }

    is_stale = age_seconds > staleness_threshold_seconds
    if (
        not is_latest
        or is_stale
        or raw_state == ProvenanceState.HISTORICAL_OBSERVATION.value
    ):
        warning = None
        if is_stale:
            warning = (
                f"Telemetry is stale: last collected {int(age_seconds)}s ago "
                f"(freshness threshold: {staleness_threshold_seconds}s)."
            )
        elif not is_latest:
            warning = "Historical stored snapshot superseded by a newer observation."
        return {
            "provenance_state": ProvenanceState.HISTORICAL_OBSERVATION.value,
            "provenance_badge": ProvenanceBadgeLabel.HISTORICAL.value,
            "is_synthetic": False,
            "is_measured": True,
            "is_stale": is_stale,
            "staleness_seconds": age_seconds,
            "staleness_warning": warning,
            "collection_status": collection_status or ("stale" if is_stale else "historical"),
            "collection_error": sanitize_collection_error(collection_error),
            "demo_mode_active": False,
        }

    return {
        "provenance_state": ProvenanceState.LIVE_TELEMETRY.value,
        "provenance_badge": ProvenanceBadgeLabel.LIVE.value,
        "is_synthetic": False,
        "is_measured": True,
        "is_stale": False,
        "staleness_seconds": age_seconds,
        "staleness_warning": None,
        "collection_status": collection_status or "success",
        "collection_error": sanitize_collection_error(collection_error),
        "demo_mode_active": False,
    }


def ensure_provenance_schema(engine: Engine) -> None:
    """Idempotently adds Phase 4 provenance columns to existing SQLite or PostgreSQL tables."""
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
    except Exception:
        return

    table_columns: dict[str, list[tuple[str, str]]] = {
        "workload_snapshots": [
            ("provenance_state", "VARCHAR(64) DEFAULT 'LIVE_TELEMETRY' NOT NULL"),
            ("source_identifier", "VARCHAR(255)"),
            ("collection_status", "VARCHAR(32) DEFAULT 'success' NOT NULL"),
            ("collection_error", "TEXT"),
            ("is_synthetic", "BOOLEAN DEFAULT FALSE NOT NULL"),
            ("is_measured", "BOOLEAN DEFAULT TRUE NOT NULL"),
        ],
        "query_statistics": [
            ("provenance_state", "VARCHAR(64) DEFAULT 'LIVE_TELEMETRY' NOT NULL"),
            ("source_identifier", "VARCHAR(255)"),
            ("query_fingerprint", "VARCHAR(64)"),
            ("captured_at", "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"),
            ("window_seconds", "FLOAT"),
            ("is_synthetic", "BOOLEAN DEFAULT FALSE NOT NULL"),
            ("is_measured", "BOOLEAN DEFAULT TRUE NOT NULL"),
        ],
        "plan_analyses": [
            ("provenance_state", "VARCHAR(64) DEFAULT 'HYPOTHETICAL_PLAN_ESTIMATE' NOT NULL"),
            ("source_identifier", "VARCHAR(255)"),
            ("is_synthetic", "BOOLEAN DEFAULT FALSE NOT NULL"),
            ("is_measured", "BOOLEAN DEFAULT FALSE NOT NULL"),
            ("model_version", "VARCHAR(128)"),
        ],
        "optimization_recommendations": [
            ("provenance_state", "VARCHAR(64) DEFAULT 'HYPOTHETICAL_PLAN_ESTIMATE' NOT NULL"),
            ("source_identifier", "VARCHAR(255)"),
            ("query_fingerprint", "VARCHAR(64)"),
            ("is_synthetic", "BOOLEAN DEFAULT FALSE NOT NULL"),
            ("is_measured", "BOOLEAN DEFAULT FALSE NOT NULL"),
            ("model_version", "VARCHAR(128)"),
        ],
        "optimization_simulations": [
            ("provenance_state", "VARCHAR(64) DEFAULT 'HYPOTHETICAL_PLAN_ESTIMATE' NOT NULL"),
            ("source_identifier", "VARCHAR(255)"),
            ("simulation_method", "VARCHAR(64) DEFAULT 'hypopg_plan_estimate' NOT NULL"),
            ("result_type", "VARCHAR(64) DEFAULT 'HYPOTHETICAL_PLAN_ESTIMATE' NOT NULL"),
            ("is_synthetic", "BOOLEAN DEFAULT FALSE NOT NULL"),
            ("is_measured", "BOOLEAN DEFAULT FALSE NOT NULL"),
            ("model_version", "VARCHAR(128)"),
        ],
    }

    with engine.begin() as conn:
        for table_name, cols in table_columns.items():
            if table_name not in existing_tables:
                continue
            existing_col_names = {c["name"] for c in inspector.get_columns(table_name)}
            for col_name, col_ddl in cols:
                if col_name not in existing_col_names:
                    try:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_ddl}"))
                    except Exception:
                        pass
