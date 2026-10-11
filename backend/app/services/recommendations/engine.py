from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.lifecycle import LifecycleState, build_observation_window_metrics
from app.core.provenance import (
    ProvenanceState,
    compute_query_fingerprint,
    sanitize_source_identifier,
)
from app.models.recommendation import OptimizationRecommendation
from app.models.workload import QueryStatistic
from app.services.recommendations.base import Recommendation
from app.services.recommendations.index import IndexAdvisor
from app.services.recommendations.join import JoinStrategyAdvisor
from app.services.recommendations.partition import PartitionAdvisor
from app.services.recommendations.query_rewrite import QueryRewriteAdvisor


class RecommendationEngine:
    def __init__(self) -> None:
        self.index = IndexAdvisor()
        self.partition = PartitionAdvisor()
        self.rewrite = QueryRewriteAdvisor()
        self.join = JoinStrategyAdvisor()

    def generate(self, db: Session, limit: int = 100) -> list[OptimizationRecommendation]:
        queries = db.query(QueryStatistic).order_by(QueryStatistic.total_exec_time_ms.desc()).limit(limit).all()
        query_by_id = {q.query_id: q for q in queries}
        all_queries_synthetic = bool(queries) and all(
            bool(q.is_synthetic) or q.provenance_state == ProvenanceState.SYNTHETIC_DEMO.value
            for q in queries
        )
        default_source = sanitize_source_identifier(get_settings().database_url)

        is_pg = db.bind is None or db.bind.dialect.name == "postgresql"
        recs: list[Recommendation] = []
        recs.extend(self.index.advise(db, limit))
        recs.extend(self.partition.advise(queries))
        recs.extend(self.rewrite.advise(queries, validate_sandbox=is_pg))
        recs.extend(self.join.advise(queries))
        persisted = []
        seen_keys: set[str] = set()
        for rec in recs:
            if rec.key in seen_keys:
                continue
            seen_keys.add(rec.key)
            existing = db.query(OptimizationRecommendation).filter_by(recommendation_key=rec.key).first()
            if existing:
                persisted.append(existing)
                continue

            matched_stats: list[QueryStatistic] = []
            for aq in rec.affected_queries or []:
                qid = aq.get("query_id") if isinstance(aq, dict) else None
                if qid is not None and int(qid) in query_by_id:
                    matched_stats.append(query_by_id[int(qid)])

            is_syn = (
                all(bool(q.is_synthetic) or q.provenance_state == ProvenanceState.SYNTHETIC_DEMO.value for q in matched_stats)
                if matched_stats
                else all_queries_synthetic
            )
            prov_state = (
                ProvenanceState.SYNTHETIC_DEMO.value
                if is_syn
                else ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
            )
            source_id = (
                "synthetic://demo-workload-generator"
                if is_syn
                else (matched_stats[0].source_identifier if matched_stats and matched_stats[0].source_identifier else default_source)
            )
            q_fp = (
                (matched_stats[0].query_fingerprint or compute_query_fingerprint(matched_stats[0].normalized_query))
                if matched_stats
                else None
            )
            baseline_payload = None
            if matched_stats:
                q0 = matched_stats[0]
                snap0 = getattr(q0, "snapshot", None)
                cap_at = q0.captured_at or (getattr(snap0, "captured_at", None) if snap0 is not None else None)
                win_sec = q0.window_seconds or (getattr(snap0, "window_seconds", None) if snap0 is not None else 60.0)
                baseline_payload = build_observation_window_metrics(
                    query_id=q0.query_id,
                    normalized_query=q0.normalized_query,
                    query_fingerprint=q_fp,
                    captured_at=cap_at,
                    window_seconds=win_sec,
                    calls=q0.calls,
                    mean_exec_time_ms=q0.mean_exec_time_ms,
                    min_exec_time_ms=q0.min_exec_time_ms,
                    max_exec_time_ms=q0.max_exec_time_ms,
                    total_exec_time_ms=q0.total_exec_time_ms,
                    rows=q0.rows,
                    shared_blks_hit=q0.shared_blks_hit,
                    shared_blks_read=q0.shared_blks_read,
                    temp_blks_read=q0.temp_blks_read,
                    temp_blks_written=q0.temp_blks_written,
                    blk_read_time_ms=q0.blk_read_time_ms,
                    blk_write_time_ms=q0.blk_write_time_ms,
                    query_frequency_per_minute=q0.query_frequency_per_minute,
                    source_identifier=source_id,
                    provenance_state=prov_state if is_syn else (q0.provenance_state or ProvenanceState.LIVE_TELEMETRY.value),
                    is_synthetic=is_syn,
                    is_measured=not is_syn,
                    environment="synthetic_demo" if is_syn else "production",
                )
            model_ver = "advisor-engine-v0.7.0"
            evidence_payload = dict(rec.evidence or {})
            evidence_payload.setdefault("provenance_state", prov_state)
            evidence_payload.setdefault("is_measured", False)
            evidence_payload.setdefault("model_version", model_ver)

            row = OptimizationRecommendation(
                recommendation_key=rec.key,
                type=rec.type,
                target=rec.target,
                proposed_change=rec.proposed_change,
                reason=rec.reason,
                evidence=evidence_payload,
                expected_benefit=rec.expected_benefit,
                risk=rec.risk,
                confidence=rec.confidence,
                affected_queries=rec.affected_queries,
                requires_approval=rec.requires_approval,
                status="pending",
                lifecycle_state=(
                    LifecycleState.AWAITING_APPROVAL.value
                    if rec.requires_approval
                    else LifecycleState.PROPOSED.value
                ),
                baseline_metrics=baseline_payload,
                provenance_state=prov_state,
                source_identifier=source_id,
                query_fingerprint=q_fp,
                is_synthetic=is_syn,
                is_measured=False,
                model_version=model_ver,
            )
            db.add(row)
            db.flush()
            persisted.append(row)
        db.commit()
        return persisted
