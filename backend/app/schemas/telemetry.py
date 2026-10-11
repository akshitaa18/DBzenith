from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.core.provenance import (
    ProvenanceBadgeLabel,
    ProvenanceState,
    badge_for_state,
    compute_query_fingerprint,
    resolve_observation_provenance,
    sanitize_source_identifier,
)


class QueryDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    query_id: int
    database_name: str | None
    user_name: str | None
    normalized_query: str
    calls: int
    total_exec_time_ms: float
    mean_exec_time_ms: float
    min_exec_time_ms: float
    max_exec_time_ms: float
    rows: int
    shared_blks_hit: int
    shared_blks_read: int
    shared_blks_dirtied: int
    shared_blks_written: int
    local_blks_hit: int
    local_blks_read: int
    temp_blks_read: int
    temp_blks_written: int
    blk_read_time_ms: float
    blk_write_time_ms: float
    query_frequency_per_minute: float
    predicate_info: dict | None
    explain_plan: list | dict | None
    optimization_summary: dict | None = None
    provenance_state: str = ProvenanceState.LIVE_TELEMETRY.value
    provenance_badge: str = ProvenanceBadgeLabel.LIVE.value
    source_identifier: str | None = None
    query_fingerprint: str | None = None
    captured_at: datetime | None = None
    window_seconds: float | None = None
    is_synthetic: bool = False
    is_measured: bool = True
    is_stale: bool = False
    staleness_warning: str | None = None

    @classmethod
    def from_model(cls, value, optimization_summary: dict | None = None, is_latest: bool = True):
        instance = cls.model_validate(value)
        if optimization_summary is not None:
            instance.optimization_summary = optimization_summary

        snap = getattr(value, "snapshot", None)
        cap_at = instance.captured_at or (getattr(snap, "captured_at", None) if snap is not None else None)
        win_sec = instance.window_seconds if instance.window_seconds is not None else (getattr(snap, "window_seconds", None) if snap is not None else None)
        raw_state = getattr(value, "provenance_state", None) or (getattr(snap, "provenance_state", None) if snap is not None else None)
        is_syn = bool(getattr(value, "is_synthetic", False)) or bool(getattr(snap, "is_synthetic", False) if snap is not None else False)
        src_id = (
            getattr(value, "source_identifier", None)
            or (getattr(snap, "source_identifier", None) if snap is not None else None)
            or ("synthetic://demo-workload-generator" if is_syn else sanitize_source_identifier(get_settings().database_url))
        )

        resolved = resolve_observation_provenance(
            provenance_state=raw_state,
            is_synthetic=is_syn,
            captured_at=cap_at,
            staleness_threshold_seconds=get_settings().telemetry_staleness_seconds,
            is_latest=is_latest,
        )
        instance.captured_at = cap_at
        instance.window_seconds = win_sec
        instance.provenance_state = resolved["provenance_state"]
        instance.provenance_badge = resolved["provenance_badge"]
        instance.source_identifier = src_id
        instance.query_fingerprint = instance.query_fingerprint or compute_query_fingerprint(instance.normalized_query)
        instance.is_synthetic = resolved["is_synthetic"]
        instance.is_measured = resolved["is_measured"]
        instance.is_stale = resolved["is_stale"]
        instance.staleness_warning = resolved["staleness_warning"]
        return instance


class PaginatedQueries(BaseModel):
    items: list[QueryDetail]
    page: int
    page_size: int
    total: int


class WorkloadSummary(BaseModel):
    snapshot_id: int | None
    captured_at: datetime | None
    window_seconds: float
    total_calls: int
    total_exec_time_ms: float
    unique_queries: int
    slow_queries: int
    top_queries: list[dict]
    provenance_state: str = ProvenanceState.HISTORICAL_OBSERVATION.value
    provenance_badge: str = ProvenanceBadgeLabel.HISTORICAL.value
    source_identifier: str | None = None
    collection_status: str = "empty"
    collection_error: str | None = None
    is_synthetic: bool = False
    is_measured: bool = False
    is_stale: bool = False
    staleness_seconds: float | None = None
    staleness_warning: str | None = None
    demo_mode_active: bool = False
