from __future__ import annotations

import hashlib
import re
from typing import Optional
from app.models.workload import QueryStatistic
from app.services.recommendations.base import Recommendation
from app.services.rewriter.engine import SQLRewriteEngine, get_rewrite_engine


class QueryRewriteAdvisor:
    def __init__(self, rewrite_engine: Optional[SQLRewriteEngine] = None):
        self.rewrite_engine = rewrite_engine or get_rewrite_engine()

    def advise(self, queries: list[QueryStatistic]) -> list[Recommendation]:
        out = []
        for q in queries:
            sql = q.normalized_query
            lower = sql.lower()

            # 1. Attempt AST-driven safe SQL rewriting
            try:
                rewrite_res = self.rewrite_engine.rewrite(sql, query_id=str(q.query_id))
                if rewrite_res.transformed and rewrite_res.is_safe:
                    trans_val = rewrite_res.transformation if isinstance(rewrite_res.transformation, str) else rewrite_res.transformation.value
                    status_val = rewrite_res.validation_status if isinstance(rewrite_res.validation_status, str) else rewrite_res.validation_status.value
                    key = hashlib.sha256(
                        f"rewrite-ast|{q.query_id}|{trans_val}".encode()
                    ).hexdigest()
                    out.append(
                        Recommendation(
                            key=key,
                            type="query_rewrite",
                            target=f"query:{q.query_id}",
                            proposed_change=f"AST Rewrite ({trans_val}): {rewrite_res.rewritten_query}",
                            reason=rewrite_res.reason,
                            evidence={
                                "original_query": rewrite_res.original_query,
                                "rewritten_query": rewrite_res.rewritten_query,
                                "transformation": trans_val,
                                "reason": rewrite_res.reason,
                                "expected_benefit": rewrite_res.expected_benefit,
                                "confidence": rewrite_res.confidence,
                                "validation_status": status_val,
                                "query_id": q.query_id,
                                "total_exec_time_ms": q.total_exec_time_ms,
                                "mean_exec_time_ms": q.mean_exec_time_ms,
                                "cost_improvement_pct": rewrite_res.cost_improvement_pct,
                                "is_safe": rewrite_res.is_safe,
                            },
                            expected_benefit=rewrite_res.expected_benefit,
                            risk="Low (AST semantic equivalence preserved and validated in sandbox)",
                            confidence=rewrite_res.confidence,
                            affected_queries=[{"query_id": q.query_id, "mean_exec_time_ms": q.mean_exec_time_ms}],
                            requires_approval=True,
                        )
                    )

            except Exception:
                # Conservative fallback if query AST parsing encounters unsupported dialect
                pass

            # 2. Existing heuristic recommendations (e.g. SELECT * or temp blks)
            if q.total_exec_time_ms >= 1000 and re.search(r"\bselect\s+\*", lower):
                key = hashlib.sha256(f"rewrite-select-star|{q.query_id}".encode()).hexdigest()
                out.append(Recommendation(key, "query_rewrite", f"query:{q.query_id}",
                    "Replace SELECT * with only required columns.",
                    "The query is expensive and requests every column, increasing row width and I/O.",
                    {"original_query": sql, "rewritten_query": None, "transformation": "PROJECTION_PRUNING", "reason": "Wide row projection overhead", "expected_benefit": "Lower network, memory, and heap/I/O work when unused columns are wide.", "confidence": 0.78, "validation_status": "pending_application_validation", "query_id": q.query_id, "total_exec_time_ms": q.total_exec_time_ms, "mean_exec_time_ms": q.mean_exec_time_ms, "rows": q.rows},
                    "Lower network, memory, and heap/I/O work when unused columns are wide.",
                    "Requires application-level validation of required columns and result shape.", 0.78,
                    [{"query_id": q.query_id, "mean_exec_time_ms": q.mean_exec_time_ms}], True))
            if q.temp_blks_read + q.temp_blks_written > 1000:
                key = hashlib.sha256(f"rewrite-temp|{q.query_id}".encode()).hexdigest()
                out.append(Recommendation(key, "query_rewrite", f"query:{q.query_id}",
                    "Reduce intermediate rows before ORDER BY/GROUP BY/window processing; review predicates and projection placement.",
                    "The query produced substantial temporary-block activity.",
                    {"original_query": sql, "rewritten_query": None, "transformation": "TEMP_SPILL_MITIGATION", "reason": "Query produced substantial temporary-block activity", "expected_benefit": "Can reduce spill-to-disk work and memory pressure.", "confidence": 0.68, "validation_status": "pending_application_validation", "query_id": q.query_id, "temp_blks_read": q.temp_blks_read, "temp_blks_written": q.temp_blks_written},
                    "Can reduce spill-to-disk work and memory pressure.",
                    "Rewrite correctness and result ordering must be validated.", 0.68,
                    [{"query_id": q.query_id, "mean_exec_time_ms": q.mean_exec_time_ms}], True))
        return out

