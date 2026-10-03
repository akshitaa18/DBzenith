"""privacy boundary audit events

Revision ID: 0003_privacy_audit
Revises: 0002_workload_telemetry
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_privacy_audit"
down_revision = "0002_workload_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "privacy_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("event", sa.String(length=100), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("query_id", sa.BigInteger(), nullable=True),
        sa.Column("structural_hash", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_privacy_audit_events_created_at", "privacy_audit_events", ["created_at"])
    op.create_index("ix_privacy_audit_events_event", "privacy_audit_events", ["event"])


def downgrade() -> None:
    op.drop_index("ix_privacy_audit_events_event", table_name="privacy_audit_events")
    op.drop_index("ix_privacy_audit_events_created_at", table_name="privacy_audit_events")
    op.drop_table("privacy_audit_events")
