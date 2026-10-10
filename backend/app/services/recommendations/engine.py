from __future__ import annotations

from sqlalchemy.orm import Session

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
        recs: list[Recommendation] = []
        recs.extend(self.index.advise(db, limit))
        recs.extend(self.partition.advise(queries))
        recs.extend(self.rewrite.advise(queries))
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
            row = OptimizationRecommendation(
                recommendation_key=rec.key, type=rec.type, target=rec.target,
                proposed_change=rec.proposed_change, reason=rec.reason, evidence=rec.evidence,
                expected_benefit=rec.expected_benefit, risk=rec.risk, confidence=rec.confidence,
                affected_queries=rec.affected_queries, requires_approval=rec.requires_approval, status="pending",
            )
            db.add(row); db.flush(); persisted.append(row)
        db.commit()
        return persisted
