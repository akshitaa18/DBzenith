"""Add workload telemetry persistence.

Revision ID: 0002_workload_telemetry
Revises: 0001_initial
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_workload_telemetry"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pg_stat_statements must be loaded by PostgreSQL at startup; the Compose
    # service enables it with shared_preload_libraries.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
    op.create_table(
        "workload_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("window_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_calls", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_exec_time_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unique_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("slow_queries", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_workload_snapshots_captured_at", "workload_snapshots", ["captured_at"])

    op.create_table(
        "query_statistics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("workload_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query_id", sa.BigInteger(), nullable=False),
        sa.Column("database_oid", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("user_oid", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("database_name", sa.Text()),
        sa.Column("user_name", sa.Text()),
        sa.Column("normalized_query", sa.Text(), nullable=False),
        sa.Column("calls", sa.BigInteger(), nullable=False),
        sa.Column("total_exec_time_ms", sa.Float(), nullable=False),
        sa.Column("mean_exec_time_ms", sa.Float(), nullable=False),
        sa.Column("min_exec_time_ms", sa.Float(), nullable=False),
        sa.Column("max_exec_time_ms", sa.Float(), nullable=False),
        sa.Column("rows", sa.BigInteger(), nullable=False),
        sa.Column("shared_blks_hit", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("shared_blks_read", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("shared_blks_dirtied", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("shared_blks_written", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("local_blks_hit", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("local_blks_read", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("temp_blks_read", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("temp_blks_written", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("blk_read_time_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("blk_write_time_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("query_frequency_per_minute", sa.Float(), nullable=False, server_default="0"),
        sa.Column("predicate_info", JSONB()),
        sa.Column("explain_plan", JSONB()),
    )
    op.create_index("ix_query_statistics_snapshot_id", "query_statistics", ["snapshot_id"])
    op.create_index("ix_query_statistics_query_id", "query_statistics", ["query_id"])
    op.create_table(
        "relation_statistics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("workload_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_name", sa.Text(), nullable=False),
        sa.Column("relation_name", sa.Text(), nullable=False),
        sa.Column("seq_scan", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("idx_scan", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("n_live_tup", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("n_dead_tup", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("table_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("index_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_index("ix_relation_statistics_snapshot_id", "relation_statistics", ["snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_relation_statistics_snapshot_id", table_name="relation_statistics")
    op.drop_table("relation_statistics")
    op.drop_index("ix_query_statistics_query_id", table_name="query_statistics")
    op.drop_index("ix_query_statistics_snapshot_id", table_name="query_statistics")
    op.drop_table("query_statistics")
    op.drop_index("ix_workload_snapshots_captured_at", table_name="workload_snapshots")
    op.drop_table("workload_snapshots")
