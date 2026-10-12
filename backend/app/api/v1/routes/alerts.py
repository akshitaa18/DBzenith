"""API routes for Configurable Workload Regression Alerts (Phase 8 Feature B)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.auth import require_analyst, require_dba, require_viewer
from app.core.provenance import badge_for_state
from app.core.security import TokenPayload
from app.db.session import get_db
from app.models.alert import AlertAuditEvent, WorkloadAlert, WorkloadAlertRule
from app.models.security import SecurityAuditEvent
from app.services.alerts.engine import (
     RegressionAlertEngine,
    SUPPORTED_ALERT_METRICS,
    ensure_default_alert_rules,
    validate_alert_rule_params,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertRuleCreateRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=128)
    description: str = Field(default="Custom deterministic workload regression rule")
    metric_name: str
    scope: str = Field(default="query")
    query_fingerprint_filter: str | None = None
    comparison_operator: str = Field(default="pct_increase")
    threshold_value: float = Field(..., ge=0.0)
    min_absolute_value: float = Field(default=0.0, ge=0.0)
    baseline_window_seconds: int = Field(default=86400, ge=60)
    comparison_window_seconds: int = Field(default=3600, ge=30)
    min_baseline_samples: int = Field(default=3, ge=1)
    min_comparison_samples: int = Field(default=2, ge=1)
    consecutive_breaches_required: int = Field(default=2, ge=1)
    allow_single_measurement: bool = False
    cooldown_seconds: int = Field(default=1800, ge=0)
    auto_resolve: bool = True
    recovery_threshold_pct: float | None = None
    severity: str = Field(default="high")
    enabled: bool = True


class AlertRuleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=128)
    description: str | None = None
    metric_name: str | None = None
    scope: str | None = None
    query_fingerprint_filter: str | None = None
    comparison_operator: str | None = None
    threshold_value: float | None = Field(default=None, ge=0.0)
    min_absolute_value: float | None = Field(default=None, ge=0.0)
    baseline_window_seconds: int | None = Field(default=None, ge=60)
    comparison_window_seconds: int | None = Field(default=None, ge=30)
    min_baseline_samples: int | None = Field(default=None, ge=1)
    min_comparison_samples: int | None = Field(default=None, ge=1)
    consecutive_breaches_required: int | None = Field(default=None, ge=1)
    allow_single_measurement: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0)
    auto_resolve: bool | None = None
    recovery_threshold_pct: float | None = None
    severity: str | None = None
    enabled: bool | None = None


class AlertActionRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=1000)


class AlertEvaluateRequest(BaseModel):
    rule_ids: list[int] | None = None


def _serialize_rule(r: WorkloadAlertRule) -> dict[str, Any]:
    return {
        "id": r.id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "rule_key": r.rule_key,
        "name": r.name,
        "description": r.description,
        "metric_name": r.metric_name,
        "metric_label": SUPPORTED_ALERT_METRICS.get(r.metric_name, {}).get("label", r.metric_name),
        "metric_unit": SUPPORTED_ALERT_METRICS.get(r.metric_name, {}).get("unit", ""),
        "scope": r.scope,
        "query_fingerprint_filter": r.query_fingerprint_filter,
        "comparison_operator": r.comparison_operator,
        "threshold_value": r.threshold_value,
        "min_absolute_value": r.min_absolute_value,
        "baseline_window_seconds": r.baseline_window_seconds,
        "comparison_window_seconds": r.comparison_window_seconds,
        "min_baseline_samples": r.min_baseline_samples,
        "min_comparison_samples": r.min_comparison_samples,
        "consecutive_breaches_required": r.consecutive_breaches_required,
        "allow_single_measurement": r.allow_single_measurement,
        "cooldown_seconds": r.cooldown_seconds,
        "auto_resolve": r.auto_resolve,
        "recovery_threshold_pct": r.recovery_threshold_pct,
        "severity": r.severity,
        "enabled": r.enabled,
        "created_by": r.created_by,
    }


def _serialize_alert(a: WorkloadAlert, audit_events: list[AlertAuditEvent] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": a.id,
        "rule_id": a.rule_id,
        "dedup_key": a.dedup_key,
        "status": a.status,
        "severity": a.severity,
        "metric_name": a.metric_name,
        "metric_label": SUPPORTED_ALERT_METRICS.get(a.metric_name, {}).get("label", a.metric_name),
        "metric_unit": SUPPORTED_ALERT_METRICS.get(a.metric_name, {}).get("unit", ""),
        "scope": a.scope,
        "title": a.title,
        "summary": a.summary,
        "started_at": a.started_at.isoformat() if a.started_at else None,
        "last_observed_at": a.last_observed_at.isoformat() if a.last_observed_at else None,
        "occurrence_count": a.occurrence_count,
        "consecutive_breaches": a.consecutive_breaches,
        "baseline_value": a.baseline_value,
        "current_value": a.current_value,
        "threshold_value": a.threshold_value,
        "deviation_pct": a.deviation_pct,
        "baseline_sample_count": a.baseline_sample_count,
        "comparison_sample_count": a.comparison_sample_count,
        "affected_query_fingerprints": a.affected_query_fingerprints or [],
        "evidence": a.evidence or {},
        "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        "acknowledged_by": a.acknowledged_by,
        "acknowledge_reason": a.acknowledge_reason,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        "resolved_by": a.resolved_by,
        "resolution_reason": a.resolution_reason,
        "resolution_type": a.resolution_type,
        "provenance_state": a.provenance_state,
        "provenance_badge": badge_for_state(a.provenance_state),
        "source_identifier": a.source_identifier,
        "is_synthetic": a.is_synthetic,
    }
    if audit_events is not None:
        payload["audit_history"] = [
            {
                "id": ev.id,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
                "alert_id": ev.alert_id,
                "rule_id": ev.rule_id,
                "action": ev.action,
                "previous_status": ev.previous_status,
                "new_status": ev.new_status,
                "actor_id": ev.actor_id,
                "actor_username": ev.actor_username,
                "actor_role": ev.actor_role,
                "reason": ev.reason,
                "details": ev.details or {},
            }
            for ev in audit_events
        ]
    return payload


@router.get("/metrics")
def list_supported_alert_metrics(
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    """Returns supported deterministic alert metrics and explicit policy on unsupported metrics."""
    return {
        "evaluation_mode": "deterministic_threshold_rules",
        "predictive_anomaly_detection_enabled": False,
        "unsupported_metrics_notice": (
            "DBZenith uses deterministic statistical threshold rules over observed PostgreSQL telemetry. "
            "Predictive ML anomaly detection and host-level OS hardware sensors (CPU temp, raw disk SMART) "
            "are explicitly unsupported unless validated telemetry sources exist."
        ),
        "supported_metrics": [
            {"metric_name": k, **v} for k, v in SUPPORTED_ALERT_METRICS.items()
        ],
    }


@router.get("/rules")
def list_alert_rules(
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    rules = ensure_default_alert_rules(db)
    return {
        "items": [_serialize_rule(r) for r in rules],
        "total": len(rules),
        "supported_metrics": list(SUPPORTED_ALERT_METRICS.keys()),
    }


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_alert_rule(
    payload: AlertRuleCreateRequest,
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_dba),
) -> dict[str, Any]:
    """Creates a new configurable regression alert rule (DBA or ADMIN required)."""
    try:
        validate_alert_rule_params(
            metric_name=payload.metric_name,
            comparison_operator=payload.comparison_operator,
            scope=payload.scope,
            threshold_value=payload.threshold_value,
            min_baseline_samples=payload.min_baseline_samples,
            min_comparison_samples=payload.min_comparison_samples,
            consecutive_breaches_required=payload.consecutive_breaches_required,
            cooldown_seconds=payload.cooldown_seconds,
            severity=payload.severity,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    raw_key = f"{payload.name}|{payload.metric_name}|{payload.scope}|{payload.query_fingerprint_filter or ''}|{datetime.now(timezone.utc).timestamp()}"
    rule_key = hashlib.sha256(raw_key.encode()).hexdigest()[:48]

    rule = WorkloadAlertRule(
        rule_key=rule_key,
        name=payload.name.strip(),
        description=payload.description.strip(),
        metric_name=payload.metric_name,
        scope=payload.scope,
        query_fingerprint_filter=payload.query_fingerprint_filter.strip() if payload.query_fingerprint_filter else None,
        comparison_operator=payload.comparison_operator,
        threshold_value=payload.threshold_value,
        min_absolute_value=payload.min_absolute_value,
        baseline_window_seconds=payload.baseline_window_seconds,
        comparison_window_seconds=payload.comparison_window_seconds,
        min_baseline_samples=payload.min_baseline_samples,
        min_comparison_samples=payload.min_comparison_samples,
        consecutive_breaches_required=payload.consecutive_breaches_required,
        allow_single_measurement=payload.allow_single_measurement,
        cooldown_seconds=payload.cooldown_seconds,
        auto_resolve=payload.auto_resolve,
        recovery_threshold_pct=payload.recovery_threshold_pct,
        severity=payload.severity,
        enabled=payload.enabled,
        created_by=user.username,
    )
    db.add(rule)
    db.flush()

    db.add(
        AlertAuditEvent(
            alert_id=None,
            rule_id=rule.id,
            action="rule_created",
            previous_status=None,
            new_status="enabled" if rule.enabled else "disabled",
            actor_id=str(user.user_id),
            actor_username=user.username,
            actor_role=user.role,
            reason=f"Created alert rule '{rule.name}' on metric '{rule.metric_name}'",
            details=_serialize_rule(rule),
        )
    )
    db.add(
        SecurityAuditEvent(
            event_category="CONFIGURATION",
            action="alert_rule_created",
            actor_id=str(user.user_id),
            actor_username=user.username,
            actor_role=user.role,
            target_entity="workload_alert_rule",
            target_id=str(rule.id),
            status="SUCCESS",
            details_json=json.dumps({"name": rule.name, "metric_name": rule.metric_name, "threshold": rule.threshold_value}),
        )
    )
    db.commit()
    db.refresh(rule)
    return _serialize_rule(rule)


@router.patch("/rules/{rule_id}")
def update_alert_rule(
    rule_id: int,
    payload: AlertRuleUpdateRequest,
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_dba),
) -> dict[str, Any]:
    """Updates an existing regression alert rule (DBA or ADMIN required)."""
    rule = db.get(WorkloadAlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alert rule {rule_id} not found")

    next_metric = payload.metric_name if payload.metric_name is not None else rule.metric_name
    next_op = payload.comparison_operator if payload.comparison_operator is not None else rule.comparison_operator
    next_scope = payload.scope if payload.scope is not None else rule.scope
    next_thresh = payload.threshold_value if payload.threshold_value is not None else rule.threshold_value
    next_min_base = payload.min_baseline_samples if payload.min_baseline_samples is not None else rule.min_baseline_samples
    next_min_comp = payload.min_comparison_samples if payload.min_comparison_samples is not None else rule.min_comparison_samples
    next_consec = payload.consecutive_breaches_required if payload.consecutive_breaches_required is not None else rule.consecutive_breaches_required
    next_cooldown = payload.cooldown_seconds if payload.cooldown_seconds is not None else rule.cooldown_seconds
    next_sev = payload.severity if payload.severity is not None else rule.severity

    try:
        validate_alert_rule_params(
            metric_name=next_metric,
            comparison_operator=next_op,
            scope=next_scope,
            threshold_value=next_thresh,
            min_baseline_samples=next_min_base,
            min_comparison_samples=next_min_comp,
            consecutive_breaches_required=next_consec,
            cooldown_seconds=next_cooldown,
            severity=next_sev,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    for field_name, val in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field_name, val)

    db.add(
        AlertAuditEvent(
            alert_id=None,
            rule_id=rule.id,
            action="rule_updated",
            previous_status="enabled",
            new_status="enabled" if rule.enabled else "disabled",
            actor_id=str(user.user_id),
            actor_username=user.username,
            actor_role=user.role,
            reason=f"Updated alert rule '{rule.name}'",
            details=payload.model_dump(exclude_unset=True),
        )
    )
    db.add(
        SecurityAuditEvent(
            event_category="CONFIGURATION",
            action="alert_rule_updated",
            actor_id=str(user.user_id),
            actor_username=user.username,
            actor_role=user.role,
            target_entity="workload_alert_rule",
            target_id=str(rule.id),
            status="SUCCESS",
            details_json=json.dumps(payload.model_dump(exclude_unset=True)),
        )
    )
    db.commit()
    db.refresh(rule)
    return _serialize_rule(rule)


@router.delete("/rules/{rule_id}")
def delete_alert_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_dba),
) -> dict[str, Any]:
    rule = db.get(WorkloadAlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alert rule {rule_id} not found")
    name = rule.name
    db.delete(rule)
    db.add(
        SecurityAuditEvent(
            event_category="CONFIGURATION",
            action="alert_rule_deleted",
            actor_id=str(user.user_id),
            actor_username=user.username,
            actor_role=user.role,
            target_entity="workload_alert_rule",
            target_id=str(rule_id),
            status="SUCCESS",
            details_json=json.dumps({"name": name}),
        )
    )
    db.commit()
    return {"status": "deleted", "rule_id": rule_id, "name": name}


@router.post("/evaluate")
def evaluate_alerts_endpoint(
    payload: AlertEvaluateRequest | None = None,
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_analyst),
) -> dict[str, Any]:
    """Evaluates enabled regression alert rules against historical and current telemetry."""
    engine = RegressionAlertEngine()
    rule_ids = payload.rule_ids if payload and payload.rule_ids else None
    return engine.evaluate(db, rule_ids=rule_ids)


@router.get("")
def list_workload_alerts(
    status_filter: str | None = Query(None, alias="status", description="Filter by: active, acknowledged, resolved"),
    severity: str | None = Query(None, description="Filter by: critical, high, warning, info"),
    metric_name: str | None = Query(None),
    scope: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    ensure_default_alert_rules(db)

    stmt = select(WorkloadAlert)
    if status_filter and status_filter.strip() and status_filter.strip().lower() != "all":
        stmt = stmt.where(func.lower(WorkloadAlert.status) == status_filter.strip().lower())
    if severity and severity.strip() and severity.strip().lower() != "all":
        stmt = stmt.where(func.lower(WorkloadAlert.severity) == severity.strip().lower())
    if metric_name and metric_name.strip() and metric_name.strip().lower() != "all":
        stmt = stmt.where(func.lower(WorkloadAlert.metric_name) == metric_name.strip().lower())
    if scope and scope.strip() and scope.strip().lower() != "all":
        stmt = stmt.where(func.lower(WorkloadAlert.scope) == scope.strip().lower())
    if search and search.strip():
        q_str = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                WorkloadAlert.title.ilike(q_str),
                WorkloadAlert.summary.ilike(q_str),
                WorkloadAlert.dedup_key.ilike(q_str),
            )
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(desc(WorkloadAlert.last_observed_at), desc(WorkloadAlert.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    active_count = db.scalar(select(func.count()).select_from(WorkloadAlert).where(WorkloadAlert.status == "active")) or 0
    ack_count = db.scalar(select(func.count()).select_from(WorkloadAlert).where(WorkloadAlert.status == "acknowledged")) or 0
    res_count = db.scalar(select(func.count()).select_from(WorkloadAlert).where(WorkloadAlert.status == "resolved")) or 0
    rules_count = db.scalar(select(func.count()).select_from(WorkloadAlertRule).where(WorkloadAlertRule.enabled.is_(True))) or 0

    return {
        "items": [_serialize_alert(a) for a in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "counts": {
            "active": active_count,
            "acknowledged": ack_count,
            "resolved": res_count,
            "enabled_rules": rules_count,
        },
        "supported_metrics": list(SUPPORTED_ALERT_METRICS.keys()),
    }


@router.get("/audit/history")
def list_alert_audit_history(
    alert_id: int | None = Query(None),
    action: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    stmt = select(AlertAuditEvent)
    if alert_id is not None:
        stmt = stmt.where(AlertAuditEvent.alert_id == alert_id)
    if action and action.strip() and action.strip().lower() != "all":
        stmt = stmt.where(func.lower(AlertAuditEvent.action) == action.strip().lower())

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    events = db.scalars(
        stmt.order_by(desc(AlertAuditEvent.created_at), desc(AlertAuditEvent.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return {
        "items": [
            {
                "id": ev.id,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
                "alert_id": ev.alert_id,
                "rule_id": ev.rule_id,
                "action": ev.action,
                "previous_status": ev.previous_status,
                "new_status": ev.new_status,
                "actor_id": ev.actor_id,
                "actor_username": ev.actor_username,
                "actor_role": ev.actor_role,
                "reason": ev.reason,
                "details": ev.details or {},
            }
            for ev in events
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/export")
def export_workload_alerts(
    format: str = Query("json", pattern="^(json|csv)$"),
    status_filter: str | None = Query(None, alias="status"),
    severity: str | None = Query(None),
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_analyst),
) -> Response:
    """Exports workload alerts and resolution history (ANALYST+ required)."""
    stmt = select(WorkloadAlert)
    if status_filter and status_filter.strip() and status_filter.strip().lower() != "all":
        stmt = stmt.where(func.lower(WorkloadAlert.status) == status_filter.strip().lower())
    if severity and severity.strip() and severity.strip().lower() != "all":
        stmt = stmt.where(func.lower(WorkloadAlert.severity) == severity.strip().lower())

    rows = db.scalars(stmt.order_by(desc(WorkloadAlert.last_observed_at), desc(WorkloadAlert.id)).limit(500)).all()

    db.add(
        SecurityAuditEvent(
            event_category="AUDIT",
            action="workload_alerts_exported",
            actor_id=str(user.user_id),
            actor_username=user.username,
            actor_role=user.role,
            target_entity="workload_alerts",
            target_id=format,
            status="SUCCESS",
            details_json=json.dumps({"format": format, "exported_count": len(rows)}),
        )
    )
    db.commit()

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "status",
                "severity",
                "metric_name",
                "scope",
                "title",
                "started_at",
                "last_observed_at",
                "occurrence_count",
                "baseline_value",
                "current_value",
                "deviation_pct",
                "acknowledged_by",
                "resolved_by",
                "resolution_type",
            ]
        )
        for a in rows:
            writer.writerow(
                [
                    a.id,
                    a.status,
                    a.severity,
                    a.metric_name,
                    a.scope,
                    a.title,
                    a.started_at.isoformat() if a.started_at else "",
                    a.last_observed_at.isoformat() if a.last_observed_at else "",
                    a.occurrence_count,
                    a.baseline_value if a.baseline_value is not None else "",
                    a.current_value if a.current_value is not None else "",
                    a.deviation_pct if a.deviation_pct is not None else "",
                    a.acknowledged_by or "",
                    a.resolved_by or "",
                    a.resolution_type or "",
                ]
            )
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="dbzenith_workload_alerts.csv"'},
        )

    return Response(
        content=json.dumps({"items": [_serialize_alert(a) for a in rows], "total": len(rows)}, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="dbzenith_workload_alerts.json"'},
    )


@router.get("/{alert_id}")
def get_workload_alert_detail(
    alert_id: int,
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    alert = db.get(WorkloadAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alert {alert_id} not found")
    events = db.scalars(
        select(AlertAuditEvent)
        .where(AlertAuditEvent.alert_id == alert_id)
        .order_by(desc(AlertAuditEvent.created_at), desc(AlertAuditEvent.id))
    ).all()
    return _serialize_alert(alert, list(events))


@router.post("/{alert_id}/acknowledge")
def acknowledge_workload_alert(
    alert_id: int,
    payload: AlertActionRequest,
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_analyst),
) -> dict[str, Any]:
    alert = db.get(WorkloadAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alert {alert_id} not found")
    if alert.status == "resolved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot acknowledge an alert that is already resolved.",
        )

    now = datetime.now(timezone.utc)
    prev_status = alert.status
    alert.status = "acknowledged"
    alert.acknowledged_at = now
    alert.acknowledged_by = user.username
    alert.acknowledge_reason = payload.reason.strip()

    db.add(
        AlertAuditEvent(
            alert_id=alert.id,
            rule_id=alert.rule_id,
            action="acknowledged",
            previous_status=prev_status,
            new_status="acknowledged",
            actor_id=str(user.user_id),
            actor_username=user.username,
            actor_role=user.role,
            reason=payload.reason.strip(),
            details={"acknowledged_at": now.isoformat()},
        )
    )
    db.add(
        SecurityAuditEvent(
            event_category="ALERT",
            action="alert_acknowledged",
            actor_id=str(user.user_id),
            actor_username=user.username,
            actor_role=user.role,
            target_entity="workload_alert",
            target_id=str(alert.id),
            status="SUCCESS",
            details_json=json.dumps({"reason": payload.reason.strip(), "previous_status": prev_status}),
        )
    )
    db.commit()
    db.refresh(alert)
    events = db.scalars(
        select(AlertAuditEvent)
        .where(AlertAuditEvent.alert_id == alert.id)
        .order_by(desc(AlertAuditEvent.created_at), desc(AlertAuditEvent.id))
    ).all()
    return _serialize_alert(alert, list(events))


@router.post("/{alert_id}/resolve")
def resolve_workload_alert(
    alert_id: int,
    payload: AlertActionRequest,
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_analyst),
) -> dict[str, Any]:
    alert = db.get(WorkloadAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alert {alert_id} not found")

    now = datetime.now(timezone.utc)
    prev_status = alert.status
    alert.status = "resolved"
    alert.resolved_at = now
    alert.resolved_by = user.username
    alert.resolution_reason = payload.reason.strip()
    alert.resolution_type = "manual"

    db.add(
        AlertAuditEvent(
            alert_id=alert.id,
            rule_id=alert.rule_id,
            action="resolved",
            previous_status=prev_status,
            new_status="resolved",
            actor_id=str(user.user_id),
            actor_username=user.username,
            actor_role=user.role,
            reason=payload.reason.strip(),
            details={"resolved_at": now.isoformat(), "resolution_type": "manual"},
        )
    )
    db.add(
        SecurityAuditEvent(
            event_category="ALERT",
            action="alert_resolved",
            actor_id=str(user.user_id),
            actor_username=user.username,
            actor_role=user.role,
            target_entity="workload_alert",
            target_id=str(alert.id),
            status="SUCCESS",
            details_json=json.dumps({"reason": payload.reason.strip(), "previous_status": prev_status}),
        )
    )
    db.commit()
    db.refresh(alert)
    events = db.scalars(
        select(AlertAuditEvent)
        .where(AlertAuditEvent.alert_id == alert.id)
        .order_by(desc(AlertAuditEvent.created_at), desc(AlertAuditEvent.id))
    ).all()
    return _serialize_alert(alert, list(events))
