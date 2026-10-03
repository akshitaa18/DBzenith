"""Persist isolated optimization simulation results.

Revision ID: 0006_simulations
Revises: 0005_recommendations
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006_simulations"
down_revision: Union[str, None] = "0005_recommendations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "optimization_simulations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("recommendation_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="completed"),
        sa.Column("baseline_cost", sa.Float(), nullable=True),
        sa.Column("proposed_cost", sa.Float(), nullable=True),
        sa.Column("improvement", sa.Float(), nullable=True),
        sa.Column("affected_queries", JSONB(), nullable=False),
        sa.Column("plan_differences", JSONB(), nullable=False),
        sa.Column("estimated_storage_impact", JSONB(), nullable=False),
        sa.Column("write_overhead_estimate", JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("limitations", JSONB(), nullable=False),
        sa.Column("benchmark", JSONB(), nullable=False),
        sa.Column("baseline_plans", JSONB(), nullable=False),
        sa.Column("proposed_plans", JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_optimization_simulations_created_at", "optimization_simulations", ["created_at"])
    op.create_index("ix_optimization_simulations_recommendation_id", "optimization_simulations", ["recommendation_id"])
    op.create_index("ix_optimization_simulations_status", "optimization_simulations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_optimization_simulations_status", table_name="optimization_simulations")
    op.drop_index("ix_optimization_simulations_recommendation_id", table_name="optimization_simulations")
    op.drop_index("ix_optimization_simulations_created_at", table_name="optimization_simulations")
    op.drop_table("optimization_simulations")
