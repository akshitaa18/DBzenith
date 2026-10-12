"""Persist sanitized execution-plan analyses.

Revision ID: 0004_plan_analysis
Revises: 0003_privacy_audit
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004_plan_analysis"
down_revision: Union[str, None] = "0003_privacy_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
    op.create_table(
        "plan_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("query_id", sa.BigInteger(), nullable=True),
        sa.Column("structural_hash", sa.String(length=64), nullable=False),
        sa.Column("sanitized_plan", json_type, nullable=False),
        sa.Column("graph", json_type, nullable=False),
        sa.Column("features", json_type, nullable=False),
        sa.Column("bottlenecks", json_type, nullable=False),
        sa.Column("explanation", json_type, nullable=False),
    )
    op.create_index("ix_plan_analyses_created_at", "plan_analyses", ["created_at"])
    op.create_index("ix_plan_analyses_query_id", "plan_analyses", ["query_id"])
    op.create_index("ix_plan_analyses_structural_hash", "plan_analyses", ["structural_hash"])


def downgrade() -> None:
    op.drop_index("ix_plan_analyses_structural_hash", table_name="plan_analyses")
    op.drop_index("ix_plan_analyses_query_id", table_name="plan_analyses")
    op.drop_index("ix_plan_analyses_created_at", table_name="plan_analyses")
    op.drop_table("plan_analyses")
