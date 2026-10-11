from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
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
