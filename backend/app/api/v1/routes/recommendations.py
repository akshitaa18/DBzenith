from __future__ import annotations

import json
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.recommendation import OptimizationRecommendation, RecommendationAuditEvent
from app.schemas.recommendations import RecommendationDecisionRequest, RecommendationPage, RecommendationResponse
from app.services.recommendations.engine import RecommendationEngine

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


def _response(row: OptimizationRecommendation) -> RecommendationResponse:
    return RecommendationResponse.model_validate(row)


@router.get("", response_model=RecommendationPage)
def list_recommendations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, pattern="^(pending|approved|rejected)$"),
    type: str | None = None,
    db: Session = Depends(get_db),
) -> RecommendationPage:
    # Generation is deterministic and idempotent; it only reads PostgreSQL telemetry/catalogs.
    RecommendationEngine().generate(db)
    query = db.query(OptimizationRecommendation)
    if status:
        query = query.filter(OptimizationRecommendation.status == status)
    if type:
        query = query.filter(OptimizationRecommendation.type == type)
    total = query.count()
    rows = query.order_by(OptimizationRecommendation.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return RecommendationPage(items=[_response(r) for r in rows], page=page, page_size=page_size, total=total)


@router.get("/audit/events")
def list_recommendation_audit_events(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Lists audit events for recommendation decisions (approvals, rejections)."""
    events = db.query(RecommendationAuditEvent).order_by(RecommendationAuditEvent.created_at.desc()).limit(50).all()
    return [
        {
            "id": e.id,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "recommendation_id": e.recommendation_id,
            "action": e.action,
            "previous_status": e.previous_status,
            "new_status": e.new_status,
            "reason": e.reason,
            "metadata": json.loads(e.metadata_json) if e.metadata_json else {},
        }
        for e in events
    ]


@router.get("/{recommendation_id}", response_model=RecommendationResponse)
def get_recommendation(recommendation_id: int, db: Session = Depends(get_db)) -> RecommendationResponse:
    row = db.get(OptimizationRecommendation, recommendation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation_not_found")
    return _response(row)


@router.get("/{recommendation_id}/trace")
def get_recommendation_trace(recommendation_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.models.simulation import OptimizationSimulation
    from app.models.workload import QueryStatistic
    from app.schemas.simulations import SimulationResponse

    row = db.get(OptimizationRecommendation, recommendation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation_not_found")

    sim = (
        db.query(OptimizationSimulation)
        .filter(OptimizationSimulation.recommendation_id == recommendation_id)
        .order_by(OptimizationSimulation.id.desc())
        .first()
    )

    audit_events = (
        db.query(RecommendationAuditEvent)
        .filter(RecommendationAuditEvent.recommendation_id == recommendation_id)
        .order_by(RecommendationAuditEvent.created_at.desc())
        .all()
    )

    matching_queries: list[dict[str, Any]] = []
    if row.affected_queries:
        for aq in row.affected_queries:
            qid = aq.get("query_id") if isinstance(aq, dict) else None
            if qid:
                stat = db.query(QueryStatistic).filter(QueryStatistic.query_id == qid).order_by(QueryStatistic.id.desc()).first()
                if stat:
                    matching_queries.append({
                        "query_id": stat.query_id,
                        "normalized_query": stat.normalized_query,
                        "mean_exec_time_ms": stat.mean_exec_time_ms,
                        "calls": stat.calls,
                        "total_exec_time_ms": stat.total_exec_time_ms,
                        "rows": stat.rows,
                        "explain_plan": stat.explain_plan,
                    })

    if not matching_queries and row.target:
        stats = (
            db.query(QueryStatistic)
            .filter(QueryStatistic.normalized_query.ilike(f"%{row.target}%"))
            .order_by(QueryStatistic.total_exec_time_ms.desc())
            .limit(3)
            .all()
        )
        for stat in stats:
            matching_queries.append({
                "query_id": stat.query_id,
                "normalized_query": stat.normalized_query,
                "mean_exec_time_ms": stat.mean_exec_time_ms,
                "calls": stat.calls,
                "total_exec_time_ms": stat.total_exec_time_ms,
                "rows": stat.rows,
                "explain_plan": stat.explain_plan,
            })

    return {
        "recommendation": _response(row).model_dump(),
        "simulation": SimulationResponse.model_validate(sim).model_dump() if sim else None,
        "audit_events": [
            {
                "id": e.id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "action": e.action,
                "previous_status": e.previous_status,
                "new_status": e.new_status,
                "reason": e.reason,
            }
            for e in audit_events
        ],
        "matching_queries": matching_queries,
    }



from fastapi import Request
from app.core.auth import get_current_user_optional, require_dba_or_admin
from app.core.security import Role, TokenPayload
from app.services.audit.recorder import AuditEventCategory, record_audit_event


def _decide(
    db: Session,
    recommendation_id: int,
    new_status: str,
    reason: str,
    request: Request | None = None,
    current_user: TokenPayload | None = None,
) -> RecommendationResponse:
    row = db.get(OptimizationRecommendation, recommendation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation_not_found")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=f"recommendation_already_{row.status}")

    # Enforce RBAC: If a user token is provided, verify it is DBA or ADMIN.
    if current_user and current_user.role not in {Role.DBA, Role.ADMIN}:
        raise HTTPException(
            status_code=403,
            detail=f"Only DBA or ADMIN roles can approve or reject recommendations (current: {current_user.role.value}).",
        )

    previous = row.status
    row.status = new_status

    # Legacy event
    db.add(RecommendationAuditEvent(
        recommendation_id=row.id, action=new_status, previous_status=previous,
        new_status=new_status, reason=reason,
        metadata_json=json.dumps({"requires_approval": row.requires_approval}),
    ))
    db.commit()
    db.refresh(row)

    # Security Audit event
    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    record_audit_event(
        db=db,
        event_category=AuditEventCategory.APPROVAL if new_status == "approved" else AuditEventCategory.REJECTION,
        action=f"recommendation_{new_status}",
        actor_id=current_user.user_id if current_user else "system",
        actor_username=current_user.username if current_user else "dba_operator",
        actor_role=current_user.role.value if current_user else "DBA",
        target_entity="OptimizationRecommendation",
        target_id=str(row.id),
        status="SUCCESS",
        ip_address=ip,
        user_agent=ua,
        details={
            "proposed_change": row.proposed_change,
            "target": row.target,
            "reason": reason,
            "previous_status": previous,
        },
    )

    return _response(row)


@router.post("/{recommendation_id}/approve", response_model=RecommendationResponse)
def approve(
    recommendation_id: int,
    request_data: RecommendationDecisionRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_user: TokenPayload | None = Depends(get_current_user_optional),
) -> RecommendationResponse:
    return _decide(db, recommendation_id, "approved", request_data.reason, req, current_user)


@router.post("/{recommendation_id}/reject", response_model=RecommendationResponse)
def reject(
    recommendation_id: int,
    request_data: RecommendationDecisionRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_user: TokenPayload | None = Depends(get_current_user_optional),
) -> RecommendationResponse:
    return _decide(db, recommendation_id, "rejected", request_data.reason, req, current_user)

