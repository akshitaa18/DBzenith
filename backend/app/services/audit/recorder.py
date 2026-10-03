"""Unified Audit Logger and Event Publisher for DBZenith.

Records:
- logins
- recommendations
- simulations
- approvals
- rejections
- migrations
- agent actions
- ai boundary inspections
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from fastapi import Request
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.security import SecurityAuditEvent

logger = get_logger("security_audit")


class AuditEventCategory:
    AUTH = "AUTH"
    RECOMMENDATION = "RECOMMENDATION"
    SIMULATION = "SIMULATION"
    APPROVAL = "APPROVAL"
    REJECTION = "REJECTION"
    MIGRATION = "MIGRATION"
    AGENT_ACTION = "AGENT_ACTION"
    AI_BOUNDARY = "AI_BOUNDARY"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"


def record_audit_event(
    db: Session,
    event_category: str,
    action: str,
    actor_id: str | None = None,
    actor_username: str | None = None,
    actor_role: str | None = None,
    target_entity: str | None = None,
    target_id: str | None = None,
    status: str = "SUCCESS",
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> SecurityAuditEvent:
    """Inserts an immutable audit record into the security audit ledger and logs to structured output."""
    details_str = json.dumps(details or {}, default=str)
    event = SecurityAuditEvent(
        event_category=event_category,
        action=action,
        actor_id=str(actor_id) if actor_id else None,
        actor_username=actor_username,
        actor_role=actor_role,
        target_entity=target_entity,
        target_id=str(target_id) if target_id else None,
        status=status,
        ip_address=ip_address,
        user_agent=user_agent,
        details_json=details_str,
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to commit audit event to database: {exc}")

    # Log to structured application logs
    logger.info(
        "security_audit_event",
        extra={
            "audit_category": event_category,
            "action": action,
            "actor": actor_username,
            "role": actor_role,
            "target": target_entity,
            "target_id": target_id,
            "status": status,
        },
    )
    return event


def audit_from_request(
    request: Request,
    db: Session,
    event_category: str,
    action: str,
    target_entity: str | None = None,
    target_id: str | None = None,
    status: str = "SUCCESS",
    details: dict[str, Any] | None = None,
) -> SecurityAuditEvent:
    """Helper to record audit events directly from an incoming FastAPI Request."""
    user = getattr(request.state, "current_user", None)
    actor_id = getattr(user, "user_id", None) if user else None
    actor_username = getattr(user, "username", None) if user else None
    actor_role = getattr(user, "role", None) if user else None
    if actor_role and hasattr(actor_role, "value"):
        actor_role = actor_role.value

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    return record_audit_event(
        db=db,
        event_category=event_category,
        action=action,
        actor_id=actor_id,
        actor_username=actor_username,
        actor_role=actor_role,
        target_entity=target_entity,
        target_id=target_id,
        status=status,
        ip_address=ip,
        user_agent=ua,
        details=details,
    )
