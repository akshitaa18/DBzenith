from __future__ import annotations

import hashlib
from typing import Any
from app.models.workload import QueryStatistic
from app.services.recommendations.base import Recommendation


class JoinStrategyAdvisor:
    def advise(self, queries: list[QueryStatistic]) -> list[Recommendation]:
        out = []
        for q in queries:
            plan = q.explain_plan
            nodes = self._nodes(plan)
            for node in nodes:
                node_type = node.get("Node Type", "")
                loops = float(node.get("Actual Loops", 0) or 0)
                total = float(node.get("Actual Total Time", 0) or 0)
                if "Nested Loop" in node_type and (loops >= 100 or total >= 50):
                    key = hashlib.sha256(f"join-nested|{q.query_id}|{node_type}".encode()).hexdigest()
                    out.append(Recommendation(key, "join_strategy", f"query:{q.query_id}",
                        "Evaluate a hash or merge join alternative after validating join cardinality and indexes.",
                        "The nested loop repeatedly executes an inner operation and has measurable execution cost.",
                        {"query_id": q.query_id, "node_type": node_type, "actual_loops": loops, "actual_total_time_ms": total},
                        "Can reduce repeated inner-side work for larger join inputs.",
                        "Alternative joins can use more memory or lose benefits for highly selective outer inputs.", 0.76,
                        [{"query_id": q.query_id, "mean_exec_time_ms": q.mean_exec_time_ms}], True))
                if node_type in {"Hash Join", "Parallel Hash Join"} and total >= 100:
                    key = hashlib.sha256(f"join-hash|{q.query_id}|{node_type}".encode()).hexdigest()
                    out.append(Recommendation(key, "join_strategy", f"query:{q.query_id}",
                        "Review hash join memory usage and compare merge/nested-loop alternatives using current cardinality statistics.",
                        "The hash join is an expensive operator in the observed plan.",
                        {"query_id": q.query_id, "node_type": node_type, "actual_total_time_ms": total},
                        "A different join strategy may reduce execution time for the observed data distribution.",
                        "Join-strategy changes are data-dependent and can regress selective workloads.", 0.64,
                        [{"query_id": q.query_id, "mean_exec_time_ms": q.mean_exec_time_ms}], True))
        return out

    def _nodes(self, plan: Any) -> list[dict]:
        if isinstance(plan, list):
            return self._nodes(plan[0]) if plan else []
        if not isinstance(plan, dict):
            return []
        result = []
        if "Plan" in plan and isinstance(plan["Plan"], dict):
            result.append(plan["Plan"])
            result.extend(self._nodes(plan["Plan"]))
        children = plan.get("Plans") or []
        for child in children:
            result.extend(self._nodes(child))
        return result
