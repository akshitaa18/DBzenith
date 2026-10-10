"""API Routes for querying the unified security audit log."""

from __future__ import annotations

import json
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import require_analyst
from app.core.security import Role, TokenPayload
from app.db.session import get_db
from app.models.security import SecurityAuditEvent

router = APIRouter(prefix="/audit", tags=["audit"])


class SecurityAuditEventItem(BaseModel):
    id: int
    timestamp: str
    event_category: str
    action: str
    actor_id: str | None = None
    actor_username: str | None = None
    actor_role: str | None = None
    target_entity: str | None = None
    target_id: str | None = None
    status: str
    ip_address: str | None = None
    user_agent: str | None = None
    details: dict[str, Any]


@router.get("", response_model=list[SecurityAuditEventItem])
def list_security_audit_events(
    category: str | None = Query(None, description="Filter by event category (AUTH, APPROVAL, MIGRATION, etc.)"),
    action: str | None = Query(None, description="Filter by action name"),
    status: str | None = Query(None, description="Filter by status (SUCCESS, FAILURE)"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_analyst),
) -> list[SecurityAuditEventItem]:
    """Retrieves chronological audit events from the immutable ledger."""
    query = db.query(SecurityAuditEvent)
    if category:
        query = query.filter(SecurityAuditEvent.event_category == category)
    if action:
        query = query.filter(SecurityAuditEvent.action == action)
    if status:
        query = query.filter(SecurityAuditEvent.status == status)

    events = query.order_by(SecurityAuditEvent.timestamp.desc()).limit(limit).all()

    results: list[SecurityAuditEventItem] = []
    for e in events:
        details = {}
        if e.details_json:
            try:
                details = json.loads(e.details_json)
            except Exception:
                details = {"raw": e.details_json}
        results.append(
            SecurityAuditEventItem(
                id=e.id,
                timestamp=e.timestamp.isoformat() if e.timestamp else "",
                event_category=e.event_category,
                action=e.action,
                actor_id=e.actor_id,
                actor_username=e.actor_username,
                actor_role=e.actor_role,
                target_entity=e.target_entity,
                target_id=e.target_id,
                status=e.status,
                ip_address=e.ip_address,
                user_agent=e.user_agent,
                details=details,
            )
        )
    return results
