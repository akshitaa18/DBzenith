from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.auth import (
    DB_CONCURRENCY_LOCK as _DECISION_LOCK,
    require_analyst,
    require_dba_or_admin,
    require_viewer,
)
from app.core.config import get_settings
from app.core.lifecycle import (
    ALLOWED_LIFECYCLE_TRANSITIONS,
    CAUSALITY_DISCLAIMER,
    EVIDENCE_GATED_STATES,
    OUTCOME_STATES,
    PRE_DECISION_STATES,
    LifecycleState,
    build_observation_window_metrics,
    calculate_impact_and_uncertainty,
    is_valid_transition,
    status_for_lifecycle_state,
)
from app.core.provenance import (
    ProvenanceState,
    compute_query_fingerprint,
    resolve_observation_provenance,
    sanitize_collection_error,
    sanitize_source_identifier,
)
from app.core.security import Role, TokenPayload
from app.db.session import get_db
from app.models.recommendation import OptimizationRecommendation, RecommendationAuditEvent
from app.models.security import SecurityAuditEvent
from app.models.simulation import OptimizationSimulation
from app.models.workload import QueryStatistic
from app.schemas.recommendations import (
    RecommendationApplyRequest,
    RecommendationDecisionRequest,
    RecommendationPage,
    RecommendationResponse,
    RecommendationTransitionRequest,
    RecommendationValidationRequest,
)
from app.schemas.simulations import SimulationResponse
from app.services.audit.recorder import AuditEventCategory, record_audit_event
from app.services.recommendations.engine import RecommendationEngine

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

_STATUS_FILTER_PATTERN = (
    "^(pending|approved|rejected|detected|analyzed|proposed|simulated|"
    "awaiting_approval|ready_for_deployment|applied|validation_pending|"
    "verified_successful|regressed|failed|inconclusive)$"
)


def _response(row: OptimizationRecommendation) -> RecommendationResponse:
    return RecommendationResponse.model_validate(row)


def _find_matching_query_stat(db: Session, row: OptimizationRecommendation, snapshot_id: int | None = None) -> QueryStatistic | None:
    if row.affected_queries:
        for aq in row.affected_queries:
            qid = aq.get("query_id") if isinstance(aq, dict) else None
            if qid is not None:
                q = db.query(QueryStatistic).filter(QueryStatistic.query_id == int(qid))
                if snapshot_id is not None:
                    q = q.filter(QueryStatistic.snapshot_id == snapshot_id)
                stat = q.order_by(QueryStatistic.id.desc()).first()
                if stat is not None:
                    return stat
    if row.target and not row.target.startswith("query:"):
        q = db.query(QueryStatistic).filter(QueryStatistic.normalized_query.ilike(f"%{row.target}%"))
        if snapshot_id is not None:
            q = q.filter(QueryStatistic.snapshot_id == snapshot_id)
        return q.order_by(QueryStatistic.total_exec_time_ms.desc()).first()
    return None


def _build_baseline_from_stat_or_evidence(db: Session, row: OptimizationRecommendation) -> dict[str, Any] | None:
    stat = _find_matching_query_stat(db, row)
    default_source = sanitize_source_identifier(get_settings().database_url)
    if stat is not None:
        snap = getattr(stat, "snapshot", None)
        cap_at = stat.captured_at or (getattr(snap, "captured_at", None) if snap is not None else None)
        win_sec = stat.window_seconds or (getattr(snap, "window_seconds", None) if snap is not None else 60.0)
        is_syn = bool(stat.is_synthetic or row.is_synthetic or (getattr(snap, "is_synthetic", False) if snap is not None else False))
        return build_observation_window_metrics(
            query_id=stat.query_id,
            normalized_query=stat.normalized_query,
            query_fingerprint=stat.query_fingerprint or row.query_fingerprint or compute_query_fingerprint(stat.normalized_query),
            captured_at=cap_at,
            window_seconds=win_sec,
            calls=stat.calls,
            mean_exec_time_ms=stat.mean_exec_time_ms,
            min_exec_time_ms=stat.min_exec_time_ms,
            max_exec_time_ms=stat.max_exec_time_ms,
            total_exec_time_ms=stat.total_exec_time_ms,
            rows=stat.rows,
            shared_blks_hit=stat.shared_blks_hit,
            shared_blks_read=stat.shared_blks_read,
            temp_blks_read=stat.temp_blks_read,
            temp_blks_written=stat.temp_blks_written,
            blk_read_time_ms=stat.blk_read_time_ms,
            blk_write_time_ms=stat.blk_write_time_ms,
            query_frequency_per_minute=stat.query_frequency_per_minute,
            source_identifier=stat.source_identifier or row.source_identifier or default_source,
            provenance_state=ProvenanceState.SYNTHETIC_DEMO.value if is_syn else (stat.provenance_state or ProvenanceState.LIVE_TELEMETRY.value),
            is_synthetic=is_syn,
            is_measured=not is_syn,
            environment="synthetic_demo" if is_syn else "production",
        )

    ev = row.evidence or {}
    mean_ms = ev.get("mean_exec_time_ms") if ev.get("mean_exec_time_ms") is not None else ev.get("mean_exec_ms")
    if mean_ms is not None:
        is_syn = bool(row.is_synthetic or row.provenance_state == ProvenanceState.SYNTHETIC_DEMO.value)
        return build_observation_window_metrics(
            query_id=ev.get("query_id"),
            normalized_query=ev.get("original_query"),
            query_fingerprint=row.query_fingerprint,
            captured_at=row.created_at,
            window_seconds=60.0,
            calls=int(ev.get("calls") or 100),
            mean_exec_time_ms=float(mean_ms),
            min_exec_time_ms=float(mean_ms) * 0.5,
            max_exec_time_ms=float(mean_ms) * 1.8,
            total_exec_time_ms=float(ev.get("total_exec_time_ms") or (float(mean_ms) * int(ev.get("calls") or 100))),
            rows=int(ev.get("rows") or 100),
            shared_blks_read=int(ev.get("shared_blks_read") or 0),
            query_frequency_per_minute=float(ev.get("query_frequency_per_minute") or 10.0),
            source_identifier=row.source_identifier or default_source,
            provenance_state=ProvenanceState.SYNTHETIC_DEMO.value if is_syn else ProvenanceState.HISTORICAL_OBSERVATION.value,
            is_synthetic=is_syn,
            is_measured=not is_syn,
            environment="synthetic_demo" if is_syn else "production",
        )
    return None


@router.get("", response_model=RecommendationPage)
def list_recommendations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, pattern=_STATUS_FILTER_PATTERN),
    lifecycle_state: str | None = Query(None, pattern=_STATUS_FILTER_PATTERN),
    type: str | None = None,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_viewer),
) -> RecommendationPage:
    # Only synthesize new recommendations for ANALYST+ roles; VIEWER strictly reads existing rows.
    if current_user.role != Role.VIEWER:
        RecommendationEngine().generate(db)
    query = db.query(OptimizationRecommendation)
    if status:
        if status in {"pending", "approved", "rejected"}:
            query = query.filter(OptimizationRecommendation.status == status)
        else:
            query = query.filter(OptimizationRecommendation.lifecycle_state == status)
    if lifecycle_state:
        query = query.filter(OptimizationRecommendation.lifecycle_state == lifecycle_state)
    if type:
        query = query.filter(OptimizationRecommendation.type == type)
    total = query.count()
    rows = (
        query.order_by(OptimizationRecommendation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return RecommendationPage(items=[_response(r) for r in rows], page=page, page_size=page_size, total=total)


@router.get("/lifecycle/summary")
def get_lifecycle_dashboard_summary(
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    """Returns aggregated lifecycle and impact tracking metrics for the DBZenith dashboard."""
    all_rows = (
        db.query(OptimizationRecommendation)
        .order_by(OptimizationRecommendation.updated_at.desc(), OptimizationRecommendation.id.desc())
        .limit(200)
        .all()
    )

    state_counts: dict[str, int] = {st.value: 0 for st in LifecycleState}
    awaiting_approval: list[dict[str, Any]] = []
    ready_for_deployment: list[dict[str, Any]] = []
    applied_changes: list[dict[str, Any]] = []
    recently_validated: list[dict[str, Any]] = []
    successful_improvements: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    failed_validations: list[dict[str, Any]] = []
    inconclusive_measurements: list[dict[str, Any]] = []

    for r in all_rows:
        resp = _response(r).model_dump()
        st = resp["lifecycle_state"]
        state_counts[st] = state_counts.get(st, 0) + 1

        if r.status == "pending" or st in PRE_DECISION_STATES:
            awaiting_approval.append(resp)
        elif st in {LifecycleState.APPROVED.value, LifecycleState.READY_FOR_DEPLOYMENT.value}:
            ready_for_deployment.append(resp)
        elif st in {LifecycleState.APPLIED.value, LifecycleState.VALIDATION_PENDING.value}:
            applied_changes.append(resp)

        if st in OUTCOME_STATES or r.validated_at is not None:
            recently_validated.append(resp)

        if st == LifecycleState.VERIFIED_SUCCESSFUL.value:
            successful_improvements.append(resp)
        elif st == LifecycleState.REGRESSED.value:
            regressions.append(resp)
        elif st == LifecycleState.FAILED.value:
            failed_validations.append(resp)
        elif st == LifecycleState.INCONCLUSIVE.value:
            inconclusive_measurements.append(resp)

    return {
        "total_recommendations": len(all_rows),
        "awaiting_approval_count": len(awaiting_approval),
        "approved_or_ready_count": len(ready_for_deployment),
        "applied_count": len(applied_changes),
        "validation_pending_count": state_counts.get(LifecycleState.VALIDATION_PENDING.value, 0),
        "verified_successful_count": len(successful_improvements),
        "regressed_count": len(regressions),
        "failed_count": len(failed_validations),
        "inconclusive_count": len(inconclusive_measurements),
        "rejected_count": state_counts.get(LifecycleState.REJECTED.value, 0),
        "counts": {
            "total": len(all_rows),
            "awaiting_approval": len(awaiting_approval),
            "ready_for_deployment": len(ready_for_deployment),
            "applied_changes": len(applied_changes),
            "recently_validated": len(recently_validated),
            "successful_improvements": len(successful_improvements),
            "regressions": len(regressions),
            "failed_validations": len(failed_validations),
            "inconclusive_measurements": len(inconclusive_measurements),
        },
        "state_counts": state_counts,
        "awaiting_approval": awaiting_approval[:15],
        "ready_for_deployment": ready_for_deployment[:15],
        "applied_changes": applied_changes[:15],
        "recently_validated": recently_validated[:15],
        "successful_improvements": successful_improvements[:15],
        "verified_improvements": successful_improvements[:15],
        "regressions": regressions[:15],
        "failed_validations": failed_validations[:15],
        "inconclusive_measurements": inconclusive_measurements[:15],
    }


@router.get("/audit/events")
def list_recommendation_audit_events(
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_analyst),
) -> list[dict[str, Any]]:
    """Lists audit events for recommendation decisions and lifecycle transitions."""
    events = db.query(RecommendationAuditEvent).order_by(RecommendationAuditEvent.created_at.desc()).limit(50).all()
    return [
        {
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
            "metadata": json.loads(e.metadata_json) if e.metadata_json else {},
        }
        for e in events
    ]


@router.get("/{recommendation_id}", response_model=RecommendationResponse)
def get_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> RecommendationResponse:
    row = db.get(OptimizationRecommendation, recommendation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation_not_found")
    return _response(row)


@router.get("/{recommendation_id}/trace")
def get_recommendation_trace(
    recommendation_id: int,
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    row = db.get(OptimizationRecommendation, recommendation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation_not_found")

    sims = (
        db.query(OptimizationSimulation)
        .filter(OptimizationSimulation.recommendation_id == recommendation_id)
        .order_by(OptimizationSimulation.id.desc())
        .all()
    )
    candidate_sim = None
    if row.candidate_simulation_id:
        candidate_sim = db.get(OptimizationSimulation, row.candidate_simulation_id)
    if candidate_sim is None and sims:
        candidate_sim = sims[0]

    audit_events = (
        db.query(RecommendationAuditEvent)
        .filter(RecommendationAuditEvent.recommendation_id == recommendation_id)
        .order_by(RecommendationAuditEvent.created_at.desc(), RecommendationAuditEvent.id.desc())
        .all()
    )

    def _serialize_matching_stat(stat: QueryStatistic) -> dict[str, Any]:
        snap = getattr(stat, "snapshot", None)
        cap_at = stat.captured_at or (getattr(snap, "captured_at", None) if snap is not None else None)
        is_syn = bool(stat.is_synthetic) or bool(getattr(snap, "is_synthetic", False) if snap is not None else False)
        raw_state = stat.provenance_state or (getattr(snap, "provenance_state", None) if snap is not None else None)
        resolved = resolve_observation_provenance(
            provenance_state=raw_state,
            is_synthetic=is_syn,
            captured_at=cap_at,
            staleness_threshold_seconds=get_settings().telemetry_staleness_seconds,
            is_latest=True,
        )
        return {
            "query_id": stat.query_id,
            "normalized_query": stat.normalized_query,
            "mean_exec_time_ms": stat.mean_exec_time_ms,
            "min_exec_time_ms": stat.min_exec_time_ms,
            "max_exec_time_ms": stat.max_exec_time_ms,
            "calls": stat.calls,
            "total_exec_time_ms": stat.total_exec_time_ms,
            "rows": stat.rows,
            "shared_blks_hit": stat.shared_blks_hit,
            "shared_blks_read": stat.shared_blks_read,
            "query_frequency_per_minute": stat.query_frequency_per_minute,
            "explain_plan": stat.explain_plan,
            "captured_at": cap_at.isoformat() if cap_at else None,
            "window_seconds": stat.window_seconds or (getattr(snap, "window_seconds", None) if snap is not None else None),
            "provenance_state": resolved["provenance_state"],
            "provenance_badge": resolved["provenance_badge"],
            "source_identifier": stat.source_identifier,
            "query_fingerprint": stat.query_fingerprint or compute_query_fingerprint(stat.normalized_query),
            "is_synthetic": resolved["is_synthetic"],
            "is_measured": resolved["is_measured"],
            "is_stale": resolved["is_stale"],
            "staleness_warning": resolved["staleness_warning"],
        }

    matching_queries: list[dict[str, Any]] = []
    if row.affected_queries:
        for aq in row.affected_queries:
            qid = aq.get("query_id") if isinstance(aq, dict) else None
            if qid:
                stat = (
                    db.query(QueryStatistic)
                    .filter(QueryStatistic.query_id == qid)
                    .order_by(QueryStatistic.id.desc())
                    .first()
                )
                if stat:
                    matching_queries.append(_serialize_matching_stat(stat))

    if not matching_queries and row.target and not row.target.startswith("query:"):
        stats = (
            db.query(QueryStatistic)
            .filter(QueryStatistic.normalized_query.ilike(f"%{row.target}%"))
            .order_by(QueryStatistic.total_exec_time_ms.desc())
            .limit(3)
            .all()
        )
        for stat in stats:
            matching_queries.append(_serialize_matching_stat(stat))

    rec_dump = _response(row).model_dump()
    cur_lc = rec_dump["lifecycle_state"]
    allowed_next = sorted(ALLOWED_LIFECYCLE_TRANSITIONS.get(cur_lc, set()))

    return {
        "recommendation": rec_dump,
        "simulation": SimulationResponse.model_validate(candidate_sim).model_dump() if candidate_sim else None,
        "simulation_history": [SimulationResponse.model_validate(s).model_dump() for s in sims],
        "audit_events": [
            {
                "id": e.id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "action": e.action,
                "previous_status": e.previous_status,
                "new_status": e.new_status,
                "previous_lifecycle_state": e.previous_lifecycle_state,
                "new_lifecycle_state": e.new_lifecycle_state,
                "actor_id": e.actor_id,
                "actor_username": e.actor_username,
                "actor_role": e.actor_role,
                "reason": e.reason,
                "metadata": json.loads(e.metadata_json) if e.metadata_json else {},
            }
            for e in audit_events
        ],
        "matching_queries": matching_queries,
        "allowed_next_states": allowed_next,
    }


def _scrub_export_dict(obj: Any) -> Any:
    """Recursively scrubs sensitive keys or credentials from exported payloads."""
    sensitive_keys = {"password", "password_hash", "salt", "secret_key", "token", "access_token", "authorization"}
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if str(k).lower() in sensitive_keys:
                continue
            if str(k).lower() in {"source_identifier", "database_url", "dsn"} and isinstance(v, str):
                cleaned[k] = sanitize_source_identifier(v)
            else:
                cleaned[k] = _scrub_export_dict(v)
        return cleaned
    if isinstance(obj, list):
        return [_scrub_export_dict(i) for i in obj]
    if isinstance(obj, str):
        return sanitize_collection_error(obj) or obj
    return obj


@router.get("/{recommendation_id}/export")
def export_recommendation_lifecycle(
    recommendation_id: int,
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_viewer),
) -> Response:
    """Exports a recommendation's full lifecycle, baseline/post-change evidence, and audit history as JSON or CSV."""
    trace = get_recommendation_trace(recommendation_id=recommendation_id, db=db, _user=current_user)
    rec = _scrub_export_dict(trace["recommendation"])
    sim = _scrub_export_dict(trace["simulation"])
    sim_history = _scrub_export_dict(trace["simulation_history"])
    audits = _scrub_export_dict(trace["audit_events"])
    baseline = rec.get("baseline_metrics") or {}
    post_change = rec.get("post_change_metrics") or {}
    impact = rec.get("impact_summary") or {}

    record_audit_event(
        db=db,
        event_category=AuditEventCategory.RECOMMENDATION,
        action="recommendation_lifecycle_exported",
        actor_id=current_user.user_id,
        actor_username=current_user.username,
        actor_role=current_user.role.value,
        target_entity="OptimizationRecommendation",
        target_id=str(recommendation_id),
        status="SUCCESS",
        details={"format": format, "lifecycle_state": rec.get("lifecycle_state")},
    )

    export_payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_by": {"username": current_user.username, "role": current_user.role.value},
        "recommendation": rec,
        "baseline_metrics": baseline,
        "candidate_simulation": sim,
        "simulation_history": sim_history,
        "post_change_metrics": post_change,
        "impact_summary": impact,
        "causality_disclaimer": CAUSALITY_DISCLAIMER,
        "approval_and_audit_history": audits,
    }

    if format == "json":
        content = json.dumps(export_payload, indent=2, default=str)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="recommendation_{recommendation_id}_lifecycle.json"'
            },
        )

    # Build structured CSV
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["section", "field", "before_value", "after_value", "delta_or_detail", "provenance_or_actor", "timestamp"])

    writer.writerow([
        "recommendation",
        "summary",
        rec.get("target"),
        rec.get("proposed_change"),
        f"status={rec.get('status')} | lifecycle={rec.get('lifecycle_state')} | risk={rec.get('risk')}",
        rec.get("provenance_state"),
        rec.get("created_at"),
    ])
    writer.writerow([
        "recommendation",
        "query_fingerprint",
        rec.get("query_fingerprint") or "",
        rec.get("source_identifier") or "",
        rec.get("reason") or "",
        rec.get("model_version") or "",
        rec.get("updated_at") or "",
    ])

    writer.writerow([
        "metrics_comparison",
        "mean_latency_ms",
        baseline.get("mean_latency_ms", ""),
        post_change.get("mean_latency_ms", ""),
        f"{impact.get('latency_improvement_pct')}%" if impact.get("latency_improvement_pct") is not None else "N/A",
        f"{baseline.get('provenance_state', '')} -> {post_change.get('provenance_state', '')}",
        post_change.get("captured_at") or baseline.get("captured_at") or "",
    ])
    writer.writerow([
        "metrics_comparison",
        "p95_latency_ms",
        baseline.get("p95_latency_ms", ""),
        post_change.get("p95_latency_ms", ""),
        f"{impact.get('p95_latency_improvement_pct')}%" if impact.get("p95_latency_improvement_pct") is not None else "N/A",
        impact.get("environment", ""),
        rec.get("validated_at") or "",
    ])
    writer.writerow([
        "metrics_comparison",
        "sample_size_calls",
        baseline.get("sample_size", ""),
        post_change.get("sample_size", ""),
        f"comparable={impact.get('is_comparable')}",
        ",".join(impact.get("incomparability_reasons") or []),
        rec.get("validated_at") or "",
    ])
    writer.writerow([
        "metrics_comparison",
        "throughput_qps",
        baseline.get("throughput_qps", ""),
        post_change.get("throughput_qps", ""),
        f"{impact.get('throughput_change_pct')}%" if impact.get("throughput_change_pct") is not None else "N/A",
        impact.get("outcome_classification", ""),
        rec.get("validated_at") or "",
    ])

    if sim:
        writer.writerow([
            "candidate_simulation",
            f"simulation_id={sim.get('id')}",
            sim.get("baseline_cost", ""),
            sim.get("proposed_cost", ""),
            f"{sim.get('improvement')}%" if sim.get("improvement") is not None else "N/A",
            sim.get("provenance_state", ""),
            sim.get("created_at", ""),
        ])

    for ev in audits:
        writer.writerow([
            "audit_event",
            ev.get("action", ""),
            ev.get("previous_lifecycle_state") or ev.get("previous_status") or "",
            ev.get("new_lifecycle_state") or ev.get("new_status") or "",
            ev.get("reason", ""),
            f"{ev.get('actor_username') or 'system'} ({ev.get('actor_role') or 'N/A'})",
            ev.get("created_at", ""),
        ])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="recommendation_{recommendation_id}_lifecycle.csv"'
        },
    )


@router.post("/{recommendation_id}/baseline", response_model=RecommendationResponse)
def capture_recommendation_baseline(
    recommendation_id: int,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_analyst),
) -> RecommendationResponse:
    """Captures or refreshes pre-change baseline telemetry metrics for a recommendation."""
    with _DECISION_LOCK:
        row = db.get(OptimizationRecommendation, recommendation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="recommendation_not_found")
        if row.applied_at is not None or row.lifecycle_state in {
            LifecycleState.APPLIED.value,
            LifecycleState.VALIDATION_PENDING.value,
            *OUTCOME_STATES,
        }:
            raise HTTPException(
                status_code=409,
                detail="cannot_overwrite_baseline_after_change_applied",
            )

        baseline = _build_baseline_from_stat_or_evidence(db, row)
        if baseline is None:
            raise HTTPException(status_code=422, detail="baseline_telemetry_unavailable")

        row.baseline_metrics = baseline
        if baseline.get("query_fingerprint") and not row.query_fingerprint:
            row.query_fingerprint = baseline["query_fingerprint"]

        prev_lc = row.lifecycle_state
        if row.lifecycle_state == LifecycleState.DETECTED.value:
            row.lifecycle_state = LifecycleState.ANALYZED.value

        db.add(
            RecommendationAuditEvent(
                recommendation_id=row.id,
                action="baseline_captured",
                previous_status=row.status,
                new_status=row.status,
                previous_lifecycle_state=prev_lc,
                new_lifecycle_state=row.lifecycle_state,
                actor_id=str(current_user.user_id),
                actor_username=current_user.username,
                actor_role=current_user.role.value,
                reason="Captured pre-change baseline telemetry window",
                metadata_json=json.dumps(
                    {
                        "sample_size": baseline.get("sample_size"),
                        "mean_latency_ms": baseline.get("mean_latency_ms"),
                        "window_seconds": baseline.get("window_seconds"),
                        "provenance_state": baseline.get("provenance_state"),
                    }
                ),
            )
        )
        db.commit()
        db.refresh(row)
        return _response(row)


def _decide(
    db: Session,
    recommendation_id: int,
    new_status: str,
    reason: str,
    request: Request | None,
    current_user: TokenPayload,
) -> RecommendationResponse:
    with _DECISION_LOCK:
        row = db.get(OptimizationRecommendation, recommendation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="recommendation_not_found")
        if row.status != "pending":
            raise HTTPException(status_code=409, detail=f"recommendation_already_{row.status}")

        if current_user.role not in {Role.DBA, Role.ADMIN}:
            raise HTTPException(
                status_code=403,
                detail=f"Only DBA or ADMIN roles can approve or reject recommendations (current: {current_user.role.value}).",
            )

        previous = row.status
        prev_lc = row.lifecycle_state or LifecycleState.AWAITING_APPROVAL.value
        new_lc = LifecycleState.APPROVED.value if new_status == "approved" else LifecycleState.REJECTED.value

        if row.baseline_metrics is None:
            row.baseline_metrics = _build_baseline_from_stat_or_evidence(db, row)

        now = datetime.now(timezone.utc)
        row.status = new_status
        row.lifecycle_state = new_lc
        row.decided_by = current_user.username
        row.decided_at = now
        row.decision_reason = reason

        db.add(
            RecommendationAuditEvent(
                recommendation_id=row.id,
                action=new_status,
                previous_status=previous,
                new_status=new_status,
                previous_lifecycle_state=prev_lc,
                new_lifecycle_state=new_lc,
                actor_id=str(current_user.user_id),
                actor_username=current_user.username,
                actor_role=current_user.role.value,
                reason=reason,
                metadata_json=json.dumps(
                    {
                        "requires_approval": row.requires_approval,
                        "decided_by": current_user.username,
                        "actor_role": current_user.role.value,
                    }
                ),
            )
        )

        ip = request.client.host if request and request.client else None
        ua = request.headers.get("user-agent") if request else None
        details = {
            "proposed_change": row.proposed_change,
            "target": row.target,
            "reason": reason,
            "previous_status": previous,
            "previous_lifecycle_state": prev_lc,
            "new_lifecycle_state": new_lc,
        }
        db.add(
            SecurityAuditEvent(
                event_category=AuditEventCategory.APPROVAL if new_status == "approved" else AuditEventCategory.REJECTION,
                action=f"recommendation_{new_status}",
                actor_id=str(current_user.user_id),
                actor_username=current_user.username,
                actor_role=current_user.role.value,
                target_entity="OptimizationRecommendation",
                target_id=str(row.id),
                status="SUCCESS",
                ip_address=ip,
                user_agent=ua,
                details_json=json.dumps(details, default=str),
            )
        )

        try:
            db.commit()
            db.refresh(row)
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail="decision_transaction_failed") from exc

        return _response(row)


@router.post("/{recommendation_id}/approve", response_model=RecommendationResponse)
def approve(
    recommendation_id: int,
    request_data: RecommendationDecisionRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_dba_or_admin),
) -> RecommendationResponse:
    return _decide(db, recommendation_id, "approved", request_data.reason, req, current_user)


@router.post("/{recommendation_id}/reject", response_model=RecommendationResponse)
def reject(
    recommendation_id: int,
    request_data: RecommendationDecisionRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_dba_or_admin),
) -> RecommendationResponse:
    return _decide(db, recommendation_id, "rejected", request_data.reason, req, current_user)


@router.post("/{recommendation_id}/transition", response_model=RecommendationResponse)
def transition_recommendation_lifecycle(
    recommendation_id: int,
    request_data: RecommendationTransitionRequest,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_analyst),
) -> RecommendationResponse:
    """Transitions a recommendation between valid workflow states.

    Strictly forbids manually marking a recommendation as applied or setting validation outcome states
    ('verified_successful', 'regressed', 'failed', 'inconclusive') via status field manipulation.
    """
    target = request_data.target_state.strip().lower()
    valid_states = {s.value for s in LifecycleState}
    if target not in valid_states:
        raise HTTPException(status_code=422, detail=f"unknown_lifecycle_state:{target}")

    if target in EVIDENCE_GATED_STATES:
        raise HTTPException(
            status_code=400,
            detail="cannot_manually_set_applied_or_outcome_state",
        )

    if target in {
        LifecycleState.APPROVED.value,
        LifecycleState.REJECTED.value,
        LifecycleState.READY_FOR_DEPLOYMENT.value,
    } and current_user.role not in {Role.DBA, Role.ADMIN}:
        raise HTTPException(
            status_code=403,
            detail="Only DBA or ADMIN roles can transition approval or deployment readiness states.",
        )

    with _DECISION_LOCK:
        row = db.get(OptimizationRecommendation, recommendation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="recommendation_not_found")

        cur_lc = row.lifecycle_state or (
            LifecycleState.APPROVED.value
            if row.status == "approved"
            else LifecycleState.REJECTED.value
            if row.status == "rejected"
            else LifecycleState.AWAITING_APPROVAL.value
        )
        if not is_valid_transition(cur_lc, target):
            raise HTTPException(
                status_code=409,
                detail=f"invalid_lifecycle_transition:{cur_lc}->{target}",
            )

        prev_status = row.status
        new_status = status_for_lifecycle_state(target, prev_status)
        row.lifecycle_state = target
        row.status = new_status
        if target in {LifecycleState.APPROVED.value, LifecycleState.REJECTED.value}:
            row.decided_by = current_user.username
            row.decided_at = datetime.now(timezone.utc)
            row.decision_reason = request_data.reason

        db.add(
            RecommendationAuditEvent(
                recommendation_id=row.id,
                action=f"transition_{target}",
                previous_status=prev_status,
                new_status=new_status,
                previous_lifecycle_state=cur_lc,
                new_lifecycle_state=target,
                actor_id=str(current_user.user_id),
                actor_username=current_user.username,
                actor_role=current_user.role.value,
                reason=request_data.reason,
                metadata_json=json.dumps({"transition": f"{cur_lc}->{target}"}),
            )
        )
        db.add(
            SecurityAuditEvent(
                event_category=AuditEventCategory.RECOMMENDATION,
                action=f"lifecycle_transition_{target}",
                actor_id=str(current_user.user_id),
                actor_username=current_user.username,
                actor_role=current_user.role.value,
                target_entity="OptimizationRecommendation",
                target_id=str(row.id),
                status="SUCCESS",
                details_json=json.dumps(
                    {
                        "previous_lifecycle_state": cur_lc,
                        "new_lifecycle_state": target,
                        "reason": request_data.reason,
                    }
                ),
            )
        )
        db.commit()
        db.refresh(row)
        return _response(row)


def _verify_change_in_catalog(db: Session, row: OptimizationRecommendation) -> tuple[bool, str]:
    """Checks the database schema catalog to verify whether a proposed index or table object exists."""
    sql = row.proposed_change or ""
    idx_match = re.search(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+CONCURRENTLY)?(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)",
        sql,
        re.I,
    )
    index_name = idx_match.group(1) if idx_match else None

    if db.bind is None:
        return False, "No active database binding available for catalog verification."

    try:
        inspector = inspect(db.bind)
        if row.target and not row.target.startswith("query:"):
            tables = set(inspector.get_table_names())
            if row.target in tables:
                indexes = inspector.get_indexes(row.target)
                existing_idx_names = {i.get("name", "").lower() for i in indexes if i.get("name")}
                if index_name and index_name.lower() in existing_idx_names:
                    return True, f"Verified index '{index_name}' on table '{row.target}' in database catalog."
                # Also check by column match if anonymous index
                col_match = re.search(r"\(([^)]+)\)", sql)
                if col_match:
                    wanted_cols = [
                        re.sub(r"\s+(ASC|DESC)\b", "", c.strip(), flags=re.I).lower()
                        for c in col_match.group(1).split(",")
                    ]
                    for idx_info in indexes:
                        idx_cols = [str(c).lower() for c in (idx_info.get("column_names") or [])]
                        if idx_cols == wanted_cols:
                            return True, f"Verified matching index on {row.target}({', '.join(wanted_cols)}) in database catalog."
    except Exception as exc:
        return False, f"Catalog inspection error: {sanitize_collection_error(str(exc))}"

    return False, "Proposed index/change was not found in the database catalog."


@router.post("/{recommendation_id}/apply", response_model=RecommendationResponse)
def apply_recommendation(
    recommendation_id: int,
    request_data: RecommendationApplyRequest,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_dba_or_admin),
) -> RecommendationResponse:
    """Marks an approved recommendation as applied ONLY when actual deployment evidence or catalog verification is confirmed.

    Never executes unapproved production DDL.
    """
    with _DECISION_LOCK:
        row = db.get(OptimizationRecommendation, recommendation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="recommendation_not_found")

        cur_lc = row.lifecycle_state or (
            LifecycleState.APPROVED.value if row.status == "approved" else LifecycleState.AWAITING_APPROVAL.value
        )
        if row.status != "approved" or cur_lc not in {
            LifecycleState.APPROVED.value,
            LifecycleState.READY_FOR_DEPLOYMENT.value,
        }:
            raise HTTPException(
                status_code=409,
                detail="recommendation_must_be_approved_before_apply",
            )

        catalog_verified = False
        verification_note = ""
        if request_data.verify_catalog:
            catalog_verified, verification_note = _verify_change_in_catalog(db, row)
            if not catalog_verified:
                raise HTTPException(
                    status_code=409,
                    detail="catalog_verification_failed_change_not_found",
                )
        else:
            ref = (request_data.deployment_reference or "").strip()
            if not request_data.confirm_applied or len(ref) < 3:
                raise HTTPException(
                    status_code=400,
                    detail="deployment_evidence_required",
                )
            verification_note = f"Confirmed by DBA with deployment reference '{ref}'."

        if row.baseline_metrics is None:
            row.baseline_metrics = _build_baseline_from_stat_or_evidence(db, row)

        now = datetime.now(timezone.utc)
        prev_lc = cur_lc
        row.lifecycle_state = LifecycleState.APPLIED.value
        row.applied_at = now
        row.deployment_details = {
            "applied_by": current_user.username,
            "applied_by_role": current_user.role.value,
            "applied_at": now.isoformat(),
            "catalog_verified": catalog_verified,
            "deployment_reference": request_data.deployment_reference,
            "verification_note": verification_note,
            "reason": request_data.reason,
        }

        db.add(
            RecommendationAuditEvent(
                recommendation_id=row.id,
                action="applied",
                previous_status=row.status,
                new_status=row.status,
                previous_lifecycle_state=prev_lc,
                new_lifecycle_state=LifecycleState.APPLIED.value,
                actor_id=str(current_user.user_id),
                actor_username=current_user.username,
                actor_role=current_user.role.value,
                reason=request_data.reason,
                metadata_json=json.dumps(row.deployment_details),
            )
        )
        db.add(
            SecurityAuditEvent(
                event_category=AuditEventCategory.MIGRATION,
                action="recommendation_applied_confirmed",
                actor_id=str(current_user.user_id),
                actor_username=current_user.username,
                actor_role=current_user.role.value,
                target_entity="OptimizationRecommendation",
                target_id=str(row.id),
                status="SUCCESS",
                details_json=json.dumps(row.deployment_details),
            )
        )
        db.commit()
        db.refresh(row)
        return _response(row)


@router.post("/{recommendation_id}/validate", response_model=RecommendationResponse)
def validate_recommendation_outcome(
    recommendation_id: int,
    request_data: RecommendationValidationRequest,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_analyst),
) -> RecommendationResponse:
    """Evaluates post-change observations against baseline metrics and computes verified impact & uncertainty."""
    with _DECISION_LOCK:
        row = db.get(OptimizationRecommendation, recommendation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="recommendation_not_found")

        if row.status == "rejected" or row.lifecycle_state == LifecycleState.REJECTED.value:
            raise HTTPException(status_code=409, detail="cannot_validate_rejected_recommendation")

        if row.status == "pending" and not request_data.use_sandbox_benchmark:
            raise HTTPException(
                status_code=409,
                detail="recommendation_must_be_approved_or_applied_before_validation",
            )

        # Ensure baseline metrics are loaded if available before validation
        baseline = row.baseline_metrics
        if baseline is None and request_data.post_change_observation is None:
            baseline = _build_baseline_from_stat_or_evidence(db, row)
            row.baseline_metrics = baseline

        sim_id = request_data.simulation_id or row.candidate_simulation_id
        candidate_sim = db.get(OptimizationSimulation, sim_id) if sim_id else None
        if candidate_sim is None:
            candidate_sim = (
                db.query(OptimizationSimulation)
                .filter(OptimizationSimulation.recommendation_id == row.id)
                .order_by(OptimizationSimulation.id.desc())
                .first()
            )
            if candidate_sim is not None and row.candidate_simulation_id is None:
                row.candidate_simulation_id = candidate_sim.id

        post_change: dict[str, Any] | None = None
        default_source = sanitize_source_identifier(get_settings().database_url)

        if request_data.post_change_observation is not None:
            obs = request_data.post_change_observation
            post_change = build_observation_window_metrics(
                query_id=obs.query_id or (baseline or {}).get("query_id"),
                normalized_query=obs.normalized_query,
                query_fingerprint=obs.query_fingerprint
                or (compute_query_fingerprint(obs.normalized_query) if obs.normalized_query else (baseline or {}).get("query_fingerprint") or row.query_fingerprint),
                captured_at=obs.captured_at or datetime.now(timezone.utc),
                window_seconds=obs.window_seconds,
                calls=obs.calls,
                mean_exec_time_ms=obs.mean_exec_time_ms,
                min_exec_time_ms=obs.min_exec_time_ms,
                max_exec_time_ms=obs.max_exec_time_ms,
                p50_latency_ms=obs.p50_latency_ms,
                p95_latency_ms=obs.p95_latency_ms,
                p99_latency_ms=obs.p99_latency_ms,
                total_exec_time_ms=obs.total_exec_time_ms,
                rows=obs.rows,
                shared_blks_hit=obs.shared_blks_hit,
                shared_blks_read=obs.shared_blks_read,
                temp_blks_read=obs.temp_blks_read,
                temp_blks_written=obs.temp_blks_written,
                blk_read_time_ms=obs.blk_read_time_ms,
                blk_write_time_ms=obs.blk_write_time_ms,
                query_frequency_per_minute=obs.query_frequency_per_minute,
                error_count=obs.error_count,
                source_identifier=obs.source_identifier or row.source_identifier or default_source,
                provenance_state=obs.provenance_state,
                is_synthetic=obs.is_synthetic or row.is_synthetic,
                is_measured=obs.is_measured and not (obs.is_synthetic or row.is_synthetic),
                environment=obs.environment,
            )
            if obs.validation_failed:
                post_change["validation_failed"] = True
            if obs.error_message:
                post_change["error_message"] = sanitize_collection_error(obs.error_message)
        elif request_data.use_sandbox_benchmark and candidate_sim is not None:
            bench = candidate_sim.benchmark or {}
            sim_lat = (
                bench.get("measured_latency_ms")
                or bench.get("simulated_latency_ms")
                or bench.get("p50_simulated_ms")
                or (
                    (bench.get("queries") or [{}])[0].get("proposed_mean_execution_ms")
                    if bench.get("queries")
                    else None
                )
            )
            is_syn = bool(candidate_sim.is_synthetic or row.is_synthetic)
            is_meas = bool(candidate_sim.is_measured or bench.get("is_measured")) and not is_syn
            runs = int(bench.get("runs") or (3 if is_meas else 1))
            post_change = build_observation_window_metrics(
                query_id=(baseline or {}).get("query_id"),
                query_fingerprint=(baseline or {}).get("query_fingerprint") or row.query_fingerprint,
                captured_at=candidate_sim.created_at or datetime.now(timezone.utc),
                window_seconds=(baseline or {}).get("window_seconds") or 60.0,
                calls=max(runs, (baseline or {}).get("sample_size") or 10),
                mean_exec_time_ms=float(sim_lat) if sim_lat is not None else None,
                min_exec_time_ms=float(sim_lat) * 0.85 if sim_lat is not None else None,
                max_exec_time_ms=float(sim_lat) * 1.25 if sim_lat is not None else None,
                error_count=1 if candidate_sim.status == "failed" or candidate_sim.error else 0,
                source_identifier=candidate_sim.source_identifier or sanitize_source_identifier(get_settings().sandbox_database_url),
                provenance_state=(
                    ProvenanceState.SYNTHETIC_DEMO.value
                    if is_syn
                    else ProvenanceState.SANDBOX_BENCHMARK.value
                    if is_meas
                    else ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
                ),
                is_synthetic=is_syn,
                is_measured=is_meas,
                environment="synthetic_demo" if is_syn else "sandbox_benchmark",
            )
            if candidate_sim.status == "failed" or candidate_sim.error:
                post_change["validation_failed"] = True
                post_change["error_message"] = sanitize_collection_error(candidate_sim.error or "Sandbox simulation failed")
        elif request_data.snapshot_id is not None:
            stat = _find_matching_query_stat(db, row, snapshot_id=request_data.snapshot_id)
            if stat is not None:
                snap = getattr(stat, "snapshot", None)
                cap_at = stat.captured_at or (getattr(snap, "captured_at", None) if snap is not None else None)
                win_sec = stat.window_seconds or (getattr(snap, "window_seconds", None) if snap is not None else 60.0)
                is_syn = bool(stat.is_synthetic or row.is_synthetic)
                post_change = build_observation_window_metrics(
                    query_id=stat.query_id,
                    normalized_query=stat.normalized_query,
                    query_fingerprint=stat.query_fingerprint or compute_query_fingerprint(stat.normalized_query),
                    captured_at=cap_at,
                    window_seconds=win_sec,
                    calls=stat.calls,
                    mean_exec_time_ms=stat.mean_exec_time_ms,
                    min_exec_time_ms=stat.min_exec_time_ms,
                    max_exec_time_ms=stat.max_exec_time_ms,
                    total_exec_time_ms=stat.total_exec_time_ms,
                    rows=stat.rows,
                    shared_blks_hit=stat.shared_blks_hit,
                    shared_blks_read=stat.shared_blks_read,
                    temp_blks_read=stat.temp_blks_read,
                    temp_blks_written=stat.temp_blks_written,
                    blk_read_time_ms=stat.blk_read_time_ms,
                    blk_write_time_ms=stat.blk_write_time_ms,
                    query_frequency_per_minute=stat.query_frequency_per_minute,
                    source_identifier=stat.source_identifier or row.source_identifier or default_source,
                    provenance_state=ProvenanceState.SYNTHETIC_DEMO.value if is_syn else (stat.provenance_state or ProvenanceState.LIVE_TELEMETRY.value),
                    is_synthetic=is_syn,
                    is_measured=bool(stat.is_measured) and not is_syn,
                    environment="synthetic_demo" if is_syn else "production",
                )

        impact = calculate_impact_and_uncertainty(
            baseline=baseline,
            post_change=post_change,
            baseline_cost=candidate_sim.baseline_cost if candidate_sim else None,
            proposed_cost=candidate_sim.proposed_cost if candidate_sim else None,
            min_sample_size=request_data.min_sample_size,
        )

        prev_lc = row.lifecycle_state or LifecycleState.APPROVED.value
        outcome_state = impact["outcome_classification"]
        now = datetime.now(timezone.utc)

        row.post_change_metrics = post_change
        row.impact_summary = impact
        row.validated_at = now
        row.lifecycle_state = outcome_state

        # Only promote provenance_state to VERIFIED_POST_CHANGE when actually applied in production and measured
        if (
            row.applied_at is not None
            and outcome_state == LifecycleState.VERIFIED_SUCCESSFUL.value
            and not impact.get("is_synthetic")
            and impact.get("is_measured")
            and impact.get("environment") == "production"
        ):
            row.provenance_state = ProvenanceState.VERIFIED_POST_CHANGE.value
            row.is_measured = True

        db.add(
            RecommendationAuditEvent(
                recommendation_id=row.id,
                action=f"validated_{outcome_state}",
                previous_status=row.status,
                new_status=row.status,
                previous_lifecycle_state=prev_lc,
                new_lifecycle_state=outcome_state,
                actor_id=str(current_user.user_id),
                actor_username=current_user.username,
                actor_role=current_user.role.value,
                reason=request_data.reason,
                metadata_json=json.dumps(
                    {
                        "outcome_classification": outcome_state,
                        "is_comparable": impact.get("is_comparable"),
                        "latency_improvement_pct": impact.get("latency_improvement_pct"),
                        "environment": impact.get("environment"),
                        "incomparability_reasons": impact.get("incomparability_reasons"),
                    }
                ),
            )
        )
        db.add(
            SecurityAuditEvent(
                event_category=AuditEventCategory.RECOMMENDATION,
                action=f"recommendation_validated_{outcome_state}",
                actor_id=str(current_user.user_id),
                actor_username=current_user.username,
                actor_role=current_user.role.value,
                target_entity="OptimizationRecommendation",
                target_id=str(row.id),
                status="FAILURE" if outcome_state == LifecycleState.FAILED.value else "SUCCESS",
                details_json=json.dumps(
                    {
                        "outcome": outcome_state,
                        "latency_improvement_pct": impact.get("latency_improvement_pct"),
                        "environment": impact.get("environment"),
                        "is_comparable": impact.get("is_comparable"),
                    }
                ),
            )
        )
        db.commit()
        db.refresh(row)
        return _response(row)
