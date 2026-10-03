"""Persist deterministic optimization recommendations and decision audits.

Revision ID: 0005_recommendations
Revises: 0004_plan_analysis
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005_recommendations"
down_revision: Union[str, None] = "0004_plan_analysis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "optimization_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("recommendation_key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("proposed_change", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.Column("expected_benefit", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("affected_queries", JSONB(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
    )
    op.create_index("ix_optimization_recommendations_created_at", "optimization_recommendations", ["created_at"])
    op.create_index("ix_optimization_recommendations_type", "optimization_recommendations", ["type"])
    op.create_index("ix_optimization_recommendations_status", "optimization_recommendations", ["status"])

    op.create_table(
        "recommendation_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("recommendation_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("previous_status", sa.String(length=20)),
        sa.Column("new_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text()),
    )
    op.create_index("ix_recommendation_audit_events_created_at", "recommendation_audit_events", ["created_at"])
    op.create_index("ix_recommendation_audit_events_recommendation_id", "recommendation_audit_events", ["recommendation_id"])


def downgrade() -> None:
    op.drop_index("ix_recommendation_audit_events_recommendation_id", table_name="recommendation_audit_events")
    op.drop_index("ix_recommendation_audit_events_created_at", table_name="recommendation_audit_events")
    op.drop_table("recommendation_audit_events")
    op.drop_index("ix_optimization_recommendations_status", table_name="optimization_recommendations")
    op.drop_index("ix_optimization_recommendations_type", table_name="optimization_recommendations")
    op.drop_index("ix_optimization_recommendations_created_at", table_name="optimization_recommendations")
    op.drop_table("optimization_recommendations")
