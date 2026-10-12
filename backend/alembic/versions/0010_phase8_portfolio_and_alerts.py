"""Add Phase 8 workload regression alerts and audit tables.

Revision ID: 0010_phase8_portfolio_and_alerts
Revises: 0009_optimization_lifecycle
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010_phase8_portfolio_and_alerts"
down_revision: Union[str, None] = "0009_optimization_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    json_type = postgresql.JSONB(astext_type=sa.Text()) if bind.dialect.name == "postgresql" else sa.JSON()

    if "workload_alert_rules" not in existing_tables:
        op.create_table(
            "workload_alert_rules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("rule_key", sa.String(length=64), unique=True, nullable=False, index=True),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("metric_name", sa.String(length=64), nullable=False, index=True),
            sa.Column("scope", sa.String(length=32), nullable=False, server_default="query"),
            sa.Column("query_fingerprint_filter", sa.String(length=128), nullable=True, index=True),
            sa.Column("comparison_operator", sa.String(length=32), nullable=False, server_default="pct_increase"),
            sa.Column("threshold_value", sa.Float(), nullable=False),
            sa.Column("min_absolute_value", sa.Float(), nullable=False, server_default="0"),
            sa.Column("baseline_window_seconds", sa.Integer(), nullable=False, server_default="86400"),
            sa.Column("comparison_window_seconds", sa.Integer(), nullable=False, server_default="3600"),
            sa.Column("min_baseline_samples", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("min_comparison_samples", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("consecutive_breaches_required", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("allow_single_measurement", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="1800"),
            sa.Column("auto_resolve", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("recovery_threshold_pct", sa.Float(), nullable=True),
            sa.Column("severity", sa.String(length=32), nullable=False, server_default="high"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true"), index=True),
            sa.Column("created_by", sa.String(length=128), nullable=True),
        )

    if "workload_alerts" not in existing_tables:
        op.create_table(
            "workload_alerts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("rule_id", sa.Integer(), sa.ForeignKey("workload_alert_rules.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("dedup_key", sa.String(length=192), nullable=False, index=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active", index=True),
            sa.Column("severity", sa.String(length=32), nullable=False, server_default="high", index=True),
            sa.Column("metric_name", sa.String(length=64), nullable=False, index=True),
            sa.Column("scope", sa.String(length=32), nullable=False, server_default="query"),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
            sa.Column("last_observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
            sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("consecutive_breaches", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("baseline_value", sa.Float(), nullable=True),
            sa.Column("current_value", sa.Float(), nullable=True),
            sa.Column("threshold_value", sa.Float(), nullable=True),
            sa.Column("deviation_pct", sa.Float(), nullable=True),
            sa.Column("baseline_sample_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("comparison_sample_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("affected_query_fingerprints", json_type, nullable=False),
            sa.Column("evidence", json_type, nullable=False),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
            sa.Column("acknowledge_reason", sa.Text(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_by", sa.String(length=128), nullable=True),
            sa.Column("resolution_reason", sa.Text(), nullable=True),
            sa.Column("resolution_type", sa.String(length=32), nullable=True),
            sa.Column("provenance_state", sa.String(length=64), nullable=False, server_default="LIVE_TELEMETRY"),
            sa.Column("source_identifier", sa.String(length=255), nullable=True),
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )

    if "alert_audit_events" not in existing_tables:
        op.create_table(
            "alert_audit_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
            sa.Column("alert_id", sa.Integer(), nullable=True, index=True),
            sa.Column("rule_id", sa.Integer(), nullable=True, index=True),
            sa.Column("action", sa.String(length=64), nullable=False, index=True),
            sa.Column("previous_status", sa.String(length=32), nullable=True),
            sa.Column("new_status", sa.String(length=32), nullable=False),
            sa.Column("actor_id", sa.String(length=64), nullable=True),
            sa.Column("actor_username", sa.String(length=128), nullable=True),
            sa.Column("actor_role", sa.String(length=32), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("details", json_type, nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for tbl in ["alert_audit_events", "workload_alerts", "workload_alert_rules"]:
        if tbl in existing_tables:
            op.drop_table(tbl)
