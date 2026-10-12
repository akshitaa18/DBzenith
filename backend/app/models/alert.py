"""Database models for Configurable Workload Regression Alerts and Audit History."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkloadAlertRule(Base):
    """Configurable deterministic threshold rule for workload and query regression alerts."""

    __tablename__ = "workload_alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    rule_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="query")
    query_fingerprint_filter: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    comparison_operator: Mapped[str] = mapped_column(String(32), nullable=False, default="pct_increase")
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    min_absolute_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    baseline_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=86400)
    comparison_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    min_baseline_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    min_comparison_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    consecutive_breaches_required: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    allow_single_measurement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    auto_resolve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    recovery_threshold_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="high")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class WorkloadAlert(Base):
    """Persisted workload or query regression alert with deduplication, evidence, and resolution state."""

    __tablename__ = "workload_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("workload_alert_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dedup_key: Mapped[str] = mapped_column(String(192), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="high", index=True)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="query")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    consecutive_breaches: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    baseline_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    deviation_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comparison_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    affected_query_fingerprints: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acknowledge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provenance_state: Mapped[str] = mapped_column(String(64), nullable=False, default="LIVE_TELEMETRY")
    source_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AlertAuditEvent(Base):
    """Immutable audit log of alert triggers, deduplicated observations, acknowledgments, and resolutions."""

    __tablename__ = "alert_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    alert_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
