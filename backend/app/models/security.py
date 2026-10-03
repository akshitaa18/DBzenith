"""Database models for Security, RBAC Users, and Unified Audit Trail."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """User account with cryptographic credential store and RBAC role."""
    __tablename__ = "security_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="VIEWER", nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityAuditEvent(Base):
    """Unified chronological security audit ledger.
    
    Tracks:
    - Logins & authentication attempts
    - Recommendations generated
    - Sandbox simulations executed
    - Human Approvals / Rejections
    - Migrations applied
    - Agent & tool actions
    - AI boundary inputs / outputs
    """
    __tablename__ = "security_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    event_category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    actor_username: Mapped[str | None] = mapped_column(String(64), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32))
    target_entity: Mapped[str | None] = mapped_column(String(128))
    target_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="SUCCESS", index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    details_json: Mapped[str | None] = mapped_column(Text)
