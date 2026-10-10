"""Create security_users and security_audit_events tables.

Revision ID: 0007_security_and_audit
Revises: 0006_simulations
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0007_security_and_audit"
down_revision: Union[str, None] = "0006_simulations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "security_users" not in existing_tables:
        op.create_table(
            "security_users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("username", sa.String(length=64), nullable=False, unique=True),
            sa.Column("email", sa.String(length=255), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(length=128), nullable=False),
            sa.Column("salt", sa.String(length=64), nullable=False),
            sa.Column("role", sa.String(length=32), server_default="VIEWER", nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_security_users_created_at", "security_users", ["created_at"])
        op.create_index("ix_security_users_username", "security_users", ["username"], unique=True)
        op.create_index("ix_security_users_email", "security_users", ["email"], unique=True)
        op.create_index("ix_security_users_role", "security_users", ["role"])

    if "security_audit_events" not in existing_tables:
        op.create_table(
            "security_audit_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("event_category", sa.String(length=64), nullable=False),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("actor_id", sa.String(length=64), nullable=True),
            sa.Column("actor_username", sa.String(length=64), nullable=True),
            sa.Column("actor_role", sa.String(length=32), nullable=True),
            sa.Column("target_entity", sa.String(length=128), nullable=True),
            sa.Column("target_id", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=32), server_default="SUCCESS", nullable=False),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=255), nullable=True),
            sa.Column("details_json", sa.Text(), nullable=True),
        )
        op.create_index("ix_security_audit_events_timestamp", "security_audit_events", ["timestamp"])
        op.create_index("ix_security_audit_events_event_category", "security_audit_events", ["event_category"])
        op.create_index("ix_security_audit_events_action", "security_audit_events", ["action"])
        op.create_index("ix_security_audit_events_actor_id", "security_audit_events", ["actor_id"])
        op.create_index("ix_security_audit_events_actor_username", "security_audit_events", ["actor_username"])
        op.create_index("ix_security_audit_events_status", "security_audit_events", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "security_audit_events" in existing_tables:
        op.drop_table("security_audit_events")
    if "security_users" in existing_tables:
        op.drop_table("security_users")
