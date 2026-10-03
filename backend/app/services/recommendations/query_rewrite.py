from __future__ import annotations

import hashlib
import re
from app.models.workload import QueryStatistic
from app.services.recommendations.base import Recommendation


class QueryRewriteAdvisor:
    def advise(self, queries: list[QueryStatistic]) -> list[Recommendation]:
        out = []
        for q in queries:
            sql = q.normalized_query
            lower = sql.lower()
            if q.total_exec_time_ms >= 1000 and re.search(r"\bselect\s+\*", lower):
                key = hashlib.sha256(f"rewrite-select-star|{q.query_id}".encode()).hexdigest()
                out.append(Recommendation(key, "query_rewrite", f"query:{q.query_id}",
                    "Replace SELECT * with only required columns.",
                    "The query is expensive and requests every column, increasing row width and I/O.",
                    {"query_id": q.query_id, "total_exec_time_ms": q.total_exec_time_ms, "mean_exec_time_ms": q.mean_exec_time_ms, "rows": q.rows},
                    "Lower network, memory, and heap/I/O work when unused columns are wide.",
                    "Requires application-level validation of required columns and result shape.", 0.78,
                    [{"query_id": q.query_id, "mean_exec_time_ms": q.mean_exec_time_ms}], True))
            if q.temp_blks_read + q.temp_blks_written > 1000:
                key = hashlib.sha256(f"rewrite-temp|{q.query_id}".encode()).hexdigest()
                out.append(Recommendation(key, "query_rewrite", f"query:{q.query_id}",
                    "Reduce intermediate rows before ORDER BY/GROUP BY/window processing; review predicates and projection placement.",
                    "The query produced substantial temporary-block activity.",
                    {"query_id": q.query_id, "temp_blks_read": q.temp_blks_read, "temp_blks_written": q.temp_blks_written},
                    "Can reduce spill-to-disk work and memory pressure.",
                    "Rewrite correctness and result ordering must be validated.", 0.68,
                    [{"query_id": q.query_id, "mean_exec_time_ms": q.mean_exec_time_ms}], True))
        return out
