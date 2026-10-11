"""API Routes for querying and exporting the unified security and operational audit logs."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
from typing import Any
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth import require_analyst
from app.core.security import TokenPayload
from app.db.session import get_db
from app.models.recommendation import RecommendationAuditEvent
from app.models.security import SecurityAuditEvent
from app.services.assistant.audit import get_assistant_audit_logger
from app.services.audit.recorder import AuditEventCategory, audit_from_request

router = APIRouter(prefix="/audit", tags=["audit"])

_SENSITIVE_EXPORT_KEYS = {
    "password",
    "password_hash",
    "salt",
    "secret_key",
    "token",
    "access_token",
    "authorization",
}


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


def _scrub_audit_dict(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _scrub_audit_dict(v)
            for k, v in obj.items()
            if str(k).lower() not in _SENSITIVE_EXPORT_KEYS
        }
    if isinstance(obj, list):
        return [_scrub_audit_dict(item) for item in obj]
    return obj


def _serialize_security_event(e: SecurityAuditEvent) -> SecurityAuditEventItem:
    details: dict[str, Any] = {}
    if e.details_json:
        try:
            details = _scrub_audit_dict(json.loads(e.details_json))
        except Exception:
            details = {"raw": e.details_json}
    return SecurityAuditEventItem(
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


def _build_security_audit_query(
    db: Session,
    category: str | None = None,
    action: str | None = None,
    status: str | None = None,
    actor: str | None = None,
    search: str | None = None,
):
    query = db.query(SecurityAuditEvent)
    if category and category.strip():
        query = query.filter(SecurityAuditEvent.event_category == category.strip().upper())
    if action and action.strip():
        query = query.filter(SecurityAuditEvent.action.ilike(f"%{action.strip()}%"))
    if status and status.strip():
        query = query.filter(SecurityAuditEvent.status == status.strip().upper())
    if actor and actor.strip():
        actor_term = actor.strip()
        query = query.filter(
            or_(
                SecurityAuditEvent.actor_username.ilike(f"%{actor_term}%"),
                SecurityAuditEvent.actor_id == actor_term,
            )
        )
    if search and search.strip():
        q = f"%{search.strip()}%"
        query = query.filter(
            or_(
                SecurityAuditEvent.event_category.ilike(q),
                SecurityAuditEvent.action.ilike(q),
                SecurityAuditEvent.actor_username.ilike(q),
                SecurityAuditEvent.actor_role.ilike(q),
                SecurityAuditEvent.target_entity.ilike(q),
                SecurityAuditEvent.target_id.ilike(q),
                SecurityAuditEvent.status.ilike(q),
                SecurityAuditEvent.details_json.ilike(q),
            )
        )
    return query.order_by(SecurityAuditEvent.timestamp.desc(), SecurityAuditEvent.id.desc())


def _build_recommendation_audit_query(
    db: Session,
    action: str | None = None,
    status: str | None = None,
    actor: str | None = None,
    search: str | None = None,
):
    query = db.query(RecommendationAuditEvent)
    if action and action.strip():
        query = query.filter(RecommendationAuditEvent.action.ilike(f"%{action.strip()}%"))
    if status and status.strip():
        st = status.strip().lower()
        query = query.filter(
            or_(
                RecommendationAuditEvent.new_status.ilike(f"%{st}%"),
                RecommendationAuditEvent.new_lifecycle_state.ilike(f"%{st}%"),
            )
        )
    if actor and actor.strip():
        actor_term = actor.strip()
        query = query.filter(
            or_(
                RecommendationAuditEvent.actor_username.ilike(f"%{actor_term}%"),
                RecommendationAuditEvent.actor_id == actor_term,
            )
        )
    if search and search.strip():
        term = search.strip()
        q = f"%{term}%"
        conds = [
            RecommendationAuditEvent.action.ilike(q),
            RecommendationAuditEvent.reason.ilike(q),
            RecommendationAuditEvent.new_status.ilike(q),
            RecommendationAuditEvent.new_lifecycle_state.ilike(q),
            RecommendationAuditEvent.actor_username.ilike(q),
        ]
        if term.lstrip("#").isdigit():
            conds.append(RecommendationAuditEvent.recommendation_id == int(term.lstrip("#")))
        query = query.filter(or_(*conds))
    return query.order_by(RecommendationAuditEvent.created_at.desc(), RecommendationAuditEvent.id.desc())


def _serialize_recommendation_event(e: RecommendationAuditEvent) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if e.metadata_json:
        try:
            meta = _scrub_audit_dict(json.loads(e.metadata_json))
        except Exception:
            meta = {}
    return {
        "id": e.id,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "recommendation_id": e.recommendation_id,
        "action": e.action,
        "previous_status": e.previous_status,
        "new_status": e.new_status,
        "previous_lifecycle_state": e.previous_lifecycle_state,
        "new_lifecycle_state": e.new_lifecycle_state,
        "actor_id": e.actor_id,
        "actor_username": e.actor_username,
        "actor_role": e.actor_role,
        "reason": e.reason,
        "metadata": meta,
    }


def _filter_assistant_events(
    action: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    raw = get_assistant_audit_logger().get_all_audit_logs(limit=500)
    filtered: list[dict[str, Any]] = []
    for item in raw:
        row = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        if action and action.strip():
            act = action.strip().lower()
            if act not in str(row.get("event_type", "")).lower() and act not in str(row.get("tool_name") or "").lower():
                continue
        if status and status.strip():
            st = status.strip().upper()
            is_auth = bool(row.get("authorized", True))
            if st in {"AUTHORIZED", "SUCCESS"} and not is_auth:
                continue
            if st in {"DENIED", "FAILURE"} and is_auth:
                continue
        if search and search.strip():
            q = search.strip().lower()
            haystack = " ".join(
                [
                    str(row.get("event_type") or ""),
                    str(row.get("tool_name") or ""),
                    str(row.get("output_summary") or ""),
                    str(row.get("session_id") or ""),
                    str(row.get("security_flag") or ""),
                ]
            ).lower()
            if q not in haystack:
                continue
        filtered.append(_scrub_audit_dict(row))
    return filtered


@router.get("", response_model=list[SecurityAuditEventItem])
def list_security_audit_events(
    category: str | None = Query(None, description="Filter by event category (AUTH, APPROVAL, MIGRATION, etc.)"),
    action: str | None = Query(None, description="Filter by action name"),
    status: str | None = Query(None, description="Filter by status (SUCCESS, FAILURE)"),
    actor: str | None = Query(None, description="Filter by actor username or ID"),
    search: str | None = Query(None, description="Free-text search across category, action, actor, target, and details"),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=500),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_analyst),
) -> list[SecurityAuditEventItem]:
    """Retrieves chronological audit events from the immutable ledger."""
    query = _build_security_audit_query(
        db=db,
        category=category,
        action=action,
        status=status,
        actor=actor,
        search=search,
    )
    effective_limit = page_size if page_size is not None else limit
    offset = (page - 1) * effective_limit if page > 1 else 0
    events = query.offset(offset).limit(effective_limit).all()
    return [_serialize_security_event(e) for e in events]


@router.get("/query")
def query_audit_ledger(
    ledger: str = Query("security", pattern="^(security|recommendations|assistant)$"),
    category: str | None = Query(None),
    action: str | None = Query(None),
    status: str | None = Query(None),
    actor: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_analyst),
) -> dict[str, Any]:
    """Server-side filtered and paginated audit query across security, recommendation, or assistant ledgers."""
    if ledger == "recommendations":
        q = _build_recommendation_audit_query(
            db=db,
            action=action,
            status=status,
            actor=actor,
            search=search,
        )
        total = q.count()
        rows = q.offset((page - 1) * page_size).limit(page_size).all()
        items = [_serialize_recommendation_event(r) for r in rows]
    elif ledger == "assistant":
        all_items = _filter_assistant_events(action=action, status=status, search=search)
        total = len(all_items)
        start = (page - 1) * page_size
        items = all_items[start : start + page_size]
    else:
        q = _build_security_audit_query(
            db=db,
            category=category,
            action=action,
            status=status,
            actor=actor,
            search=search,
        )
        total = q.count()
        rows = q.offset((page - 1) * page_size).limit(page_size).all()
        items = [_serialize_security_event(r).model_dump() for r in rows]

    return {
        "ledger": ledger,
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "immutable": True,
    }


@router.get("/export")
def export_audit_ledger(
    request: Request,
    ledger: str = Query("security", pattern="^(security|recommendations|assistant)$"),
    format: str = Query("json", pattern="^(json|csv)$"),
    category: str | None = Query(None),
    action: str | None = Query(None),
    status: str | None = Query(None),
    actor: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_analyst),
) -> Response:
    """Exports filtered audit records in JSON or CSV format (ANALYST+ access-controlled) and logs the export."""
    if ledger == "recommendations":
        rows = _build_recommendation_audit_query(
            db=db,
            action=action,
            status=status,
            actor=actor,
            search=search,
        ).limit(limit).all()
        records = [_serialize_recommendation_event(r) for r in rows]
    elif ledger == "assistant":
        records = _filter_assistant_events(action=action, status=status, search=search)[:limit]
    else:
        rows = _build_security_audit_query(
            db=db,
            category=category,
            action=action,
            status=status,
            actor=actor,
            search=search,
        ).limit(limit).all()
        records = [_serialize_security_event(r).model_dump() for r in rows]

    audit_from_request(
        request,
        db,
        event_category=AuditEventCategory.AUTH,
        action="audit_ledger_exported",
        target_entity="AuditLedger",
        target_id=ledger,
        status="SUCCESS",
        details={
            "ledger": ledger,
            "format": format,
            "exported_count": len(records),
            "filters": {
                "category": category,
                "action": action,
                "status": status,
                "actor": actor,
                "search": search,
            },
        },
    )

    filename = f"dbzenith_{ledger}_audit_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.{format}"
    if format == "json":
        payload = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "exported_by": {
                "user_id": current_user.user_id,
                "username": current_user.username,
                "role": current_user.role.value,
            },
            "ledger": ledger,
            "immutable_ledger": True,
            "record_count": len(records),
            "records": records,
        }
        return Response(
            content=json.dumps(payload, indent=2, default=str),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    if ledger == "recommendations":
        writer.writerow([
            "id",
            "created_at",
            "recommendation_id",
            "action",
            "previous_status",
            "new_status",
            "previous_lifecycle_state",
            "new_lifecycle_state",
            "actor_username",
            "actor_role",
            "reason",
        ])
        for r in records:
            writer.writerow([
                r.get("id"),
                r.get("created_at") or "",
                r.get("recommendation_id"),
                r.get("action") or "",
                r.get("previous_status") or "",
                r.get("new_status") or "",
                r.get("previous_lifecycle_state") or "",
                r.get("new_lifecycle_state") or "",
                r.get("actor_username") or "system",
                r.get("actor_role") or "SYSTEM",
                r.get("reason") or "",
            ])
    elif ledger == "assistant":
        writer.writerow([
            "timestamp",
            "session_id",
            "event_type",
            "tool_name",
            "authorized",
            "security_flag",
            "output_summary",
        ])
        for r in records:
            writer.writerow([
                r.get("timestamp") or "",
                r.get("session_id") or "",
                r.get("event_type") or "",
                r.get("tool_name") or "",
                r.get("authorized"),
                r.get("security_flag") or "",
                r.get("output_summary") or "",
            ])
    else:
        writer.writerow([
            "id",
            "timestamp",
            "event_category",
            "action",
            "actor_username",
            "actor_role",
            "target_entity",
            "target_id",
            "status",
            "ip_address",
        ])
        for r in records:
            writer.writerow([
                r.get("id"),
                r.get("timestamp") or "",
                r.get("event_category") or "",
                r.get("action") or "",
                r.get("actor_username") or r.get("actor_id") or "system",
                r.get("actor_role") or "SYSTEM",
                r.get("target_entity") or "",
                r.get("target_id") or "",
                r.get("status") or "",
                r.get("ip_address") or "",
            ])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

