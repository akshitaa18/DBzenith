from __future__ import annotations

import hashlib
import re
from app.models.workload import QueryStatistic
from app.services.recommendations.base import Recommendation
from app.services.recommendations.parsing import parse_query_shape


class PartitionAdvisor:
    def advise(self, queries: list[QueryStatistic]) -> list[Recommendation]:
        out = []
        for q in queries:
            shape = parse_query_shape(q.normalized_query)
            if not shape.relations or not q.explain_plan:
                continue
            if q.total_exec_time_ms < 5000 and q.query_frequency_per_minute < 30:
                continue
            range_predicates = [c for _, c in shape.where_columns if re.search(r"date|time|timestamp|created|updated", c, re.I)]
            if not range_predicates:
                continue
            rel = shape.relations[0]
            key = hashlib.sha256(f"partition|{rel}|{range_predicates[0]}".encode()).hexdigest()
            out.append(Recommendation(key, "partition_by_range", rel,
                f"Evaluate RANGE partitioning on {rel} by {range_predicates[0]} (after validating retention and cross-partition query patterns).",
                "A high-cost, frequently executed workload repeatedly filters a time-like column, which is a candidate for partition pruning.",
                {"query_id": q.query_id, "total_exec_time_ms": q.total_exec_time_ms, "calls": q.calls, "frequency_per_minute": q.query_frequency_per_minute, "candidate_column": range_predicates[0]},
                "Potentially limits scanned data for time-bounded queries and simplifies retention operations.",
                "Partitioning adds operational complexity and can hurt queries that do not constrain the partition key.",
                0.72, [{"query_id": q.query_id, "mean_exec_time_ms": q.mean_exec_time_ms}], True))
        return out
