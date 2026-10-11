"""Add Phase 4 data provenance and telemetry transparency columns.

Revision ID: 0008_data_provenance
Revises: 0007_security_and_audit
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0008_data_provenance"
down_revision: Union[str, None] = "0007_security_and_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(table_name: str, column: sa.Column, existing_cols: set[str]) -> None:
    if column.name not in existing_cols:
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "workload_snapshots" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("workload_snapshots")}
        _add_column_if_missing(
            "workload_snapshots",
            sa.Column("provenance_state", sa.String(length=64), server_default="LIVE_TELEMETRY", nullable=False),
            cols,
        )
        _add_column_if_missing(
            "workload_snapshots",
            sa.Column("source_identifier", sa.String(length=255), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "workload_snapshots",
            sa.Column("collection_status", sa.String(length=32), server_default="success", nullable=False),
            cols,
        )
        _add_column_if_missing(
            "workload_snapshots",
            sa.Column("collection_error", sa.Text(), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "workload_snapshots",
            sa.Column("is_synthetic", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            cols,
        )
        _add_column_if_missing(
            "workload_snapshots",
            sa.Column("is_measured", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            cols,
        )

    if "query_statistics" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("query_statistics")}
        _add_column_if_missing(
            "query_statistics",
            sa.Column("provenance_state", sa.String(length=64), server_default="LIVE_TELEMETRY", nullable=False),
            cols,
        )
        _add_column_if_missing(
            "query_statistics",
            sa.Column("source_identifier", sa.String(length=255), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "query_statistics",
            sa.Column("query_fingerprint", sa.String(length=64), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "query_statistics",
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "query_statistics",
            sa.Column("window_seconds", sa.Float(), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "query_statistics",
            sa.Column("is_synthetic", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            cols,
        )
        _add_column_if_missing(
            "query_statistics",
            sa.Column("is_measured", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            cols,
        )

    if "plan_analyses" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("plan_analyses")}
        _add_column_if_missing(
            "plan_analyses",
            sa.Column("provenance_state", sa.String(length=64), server_default="HYPOTHETICAL_PLAN_ESTIMATE", nullable=False),
            cols,
        )
        _add_column_if_missing(
            "plan_analyses",
            sa.Column("source_identifier", sa.String(length=255), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "plan_analyses",
            sa.Column("is_synthetic", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            cols,
        )
        _add_column_if_missing(
            "plan_analyses",
            sa.Column("is_measured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            cols,
        )
        _add_column_if_missing(
            "plan_analyses",
            sa.Column("model_version", sa.String(length=128), nullable=True),
            cols,
        )

    if "optimization_recommendations" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("optimization_recommendations")}
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("provenance_state", sa.String(length=64), server_default="HYPOTHETICAL_PLAN_ESTIMATE", nullable=False),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("source_identifier", sa.String(length=255), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("query_fingerprint", sa.String(length=64), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("is_synthetic", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("is_measured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("model_version", sa.String(length=128), nullable=True),
            cols,
        )

    if "optimization_simulations" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("optimization_simulations")}
        _add_column_if_missing(
            "optimization_simulations",
            sa.Column("provenance_state", sa.String(length=64), server_default="HYPOTHETICAL_PLAN_ESTIMATE", nullable=False),
            cols,
        )
        _add_column_if_missing(
            "optimization_simulations",
            sa.Column("source_identifier", sa.String(length=255), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_simulations",
            sa.Column("simulation_method", sa.String(length=64), server_default="hypopg_plan_estimate", nullable=False),
            cols,
        )
        _add_column_if_missing(
            "optimization_simulations",
            sa.Column("result_type", sa.String(length=64), server_default="HYPOTHETICAL_PLAN_ESTIMATE", nullable=False),
            cols,
        )
        _add_column_if_missing(
            "optimization_simulations",
            sa.Column("is_synthetic", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            cols,
        )
        _add_column_if_missing(
            "optimization_simulations",
            sa.Column("is_measured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            cols,
        )
        _add_column_if_missing(
            "optimization_simulations",
            sa.Column("model_version", sa.String(length=128), nullable=True),
            cols,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    drop_map = {
        "workload_snapshots": ["provenance_state", "source_identifier", "collection_status", "collection_error", "is_synthetic", "is_measured"],
        "query_statistics": ["provenance_state", "source_identifier", "query_fingerprint", "captured_at", "window_seconds", "is_synthetic", "is_measured"],
        "plan_analyses": ["provenance_state", "source_identifier", "is_synthetic", "is_measured", "model_version"],
        "optimization_recommendations": ["provenance_state", "source_identifier", "query_fingerprint", "is_synthetic", "is_measured", "model_version"],
        "optimization_simulations": ["provenance_state", "source_identifier", "simulation_method", "result_type", "is_synthetic", "is_measured", "model_version"],
    }
    for table_name, col_names in drop_map.items():
        if table_name in existing_tables:
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in col_names:
                if col in existing_cols:
                    op.drop_column(table_name, col)
