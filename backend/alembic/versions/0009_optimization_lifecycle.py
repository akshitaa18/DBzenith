"""Add Phase 5 optimization lifecycle and impact tracking columns.

Revision ID: 0009_optimization_lifecycle
Revises: 0008_data_provenance
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009_optimization_lifecycle"
down_revision: Union[str, None] = "0008_data_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(table_name: str, column: sa.Column, existing_cols: set[str]) -> None:
    if column.name not in existing_cols:
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    json_type = postgresql.JSONB(astext_type=sa.Text()) if bind.dialect.name == "postgresql" else sa.JSON()

    if "optimization_recommendations" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("optimization_recommendations")}
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("lifecycle_state", sa.String(length=64), server_default="awaiting_approval", nullable=False),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("candidate_simulation_id", sa.BigInteger(), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("baseline_metrics", json_type, nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("post_change_metrics", json_type, nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("impact_summary", json_type, nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("deployment_details", json_type, nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("decided_by", sa.String(length=128), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("decision_reason", sa.Text(), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "optimization_recommendations",
            sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
            cols,
        )

    if "recommendation_audit_events" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("recommendation_audit_events")}
        _add_column_if_missing(
            "recommendation_audit_events",
            sa.Column("previous_lifecycle_state", sa.String(length=64), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "recommendation_audit_events",
            sa.Column("new_lifecycle_state", sa.String(length=64), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "recommendation_audit_events",
            sa.Column("actor_id", sa.String(length=64), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "recommendation_audit_events",
            sa.Column("actor_username", sa.String(length=128), nullable=True),
            cols,
        )
        _add_column_if_missing(
            "recommendation_audit_events",
            sa.Column("actor_role", sa.String(length=32), nullable=True),
            cols,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    drop_map = {
        "optimization_recommendations": [
            "lifecycle_state",
            "candidate_simulation_id",
            "baseline_metrics",
            "post_change_metrics",
            "impact_summary",
            "deployment_details",
            "decided_by",
            "decided_at",
            "decision_reason",
            "applied_at",
            "validated_at",
        ],
        "recommendation_audit_events": [
            "previous_lifecycle_state",
            "new_lifecycle_state",
            "actor_id",
            "actor_username",
            "actor_role",
        ],
    }
    for table_name, col_names in drop_map.items():
        if table_name in existing_tables:
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in col_names:
                if col in existing_cols:
                    op.drop_column(table_name, col)
