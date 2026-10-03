from __future__ import annotations

from app.services.plans.models import Bottleneck, PlanGraph


def _severity(score: float) -> str:
    return "critical" if score >= 0.9 else "high" if score >= 0.65 else "medium"


def detect_bottlenecks(graph: PlanGraph) -> list[Bottleneck]:
    result: list[Bottleneck] = []
    nodes = list(graph.nodes.values())
    for n in nodes:
        loops = n.actual_loops or 0
        actual = n.actual_rows if n.actual_rows is not None else None
        if n.node_type in {"Seq Scan", "Parallel Seq Scan"} and n.relation:
            evidence = {"node_type": n.node_type, "relation": n.relation, "total_cost": n.total_cost}
            result.append(Bottleneck("sequential_scan", _severity(min(1.0, n.total_cost / 1000)), evidence, n.node_id,
                "A sequential scan reads the relation without using an index; this can dominate work as relation size grows.",
                "Review selective predicates and consider an appropriate index after validating workload selectivity and write cost."))
        if n.node_type in {"Nested Loop", "Nested Loop Left Join", "Nested Loop Semi Join", "Nested Loop Anti Join"} and loops >= 100:
            result.append(Bottleneck("high_loop_count", "high", {"actual_loops": loops}, n.node_id,
                "The join node executed its inner side many times, multiplying the cost of downstream work.",
                "Check join cardinality estimates and indexes on the inner-side join keys; compare with hash or merge join alternatives."))
        if n.node_type in {"Sort", "Incremental Sort"} and n.actual_total_time_ms and n.actual_total_time_ms >= 10:
            result.append(Bottleneck("expensive_sort", "high" if n.actual_total_time_ms >= 100 else "medium",
                {"actual_total_time_ms": n.actual_total_time_ms, "total_cost": n.total_cost}, n.node_id,
                "Sorting consumed substantial execution time.",
                "Consider indexes that provide the required order, reducing rows before sorting, or reviewing work_mem when appropriate."))
        if n.actual_total_time_ms is not None and n.actual_total_time_ms >= 25 and n.node_type not in {"Sort", "Incremental Sort"}:
            result.append(Bottleneck("expensive_operator", "critical" if n.actual_total_time_ms >= 250 else "high" if n.actual_total_time_ms >= 100 else "medium",
                {"node_type": n.node_type, "actual_total_time_ms": n.actual_total_time_ms, "total_cost": n.total_cost}, n.node_id,
                "This operator consumed a substantial share of measured execution time.",
                "Inspect the operator's input cardinality and access path; reduce rows earlier or choose an alternative access/join strategy where supported."))
        if actual is not None and n.plan_rows > 0:
            ratio = max(actual, 0.001) / n.plan_rows
            if ratio >= 10 or ratio <= 0.1:
                result.append(Bottleneck("row_estimation_error", "high" if ratio >= 100 or ratio <= 0.01 else "medium",
                    {"estimated_rows": n.plan_rows, "actual_rows": actual, "ratio": round(ratio, 3)}, n.node_id,
                    "Estimated and actual row counts differ substantially, which can lead PostgreSQL to choose a poor plan.",
                    "Refresh statistics with ANALYZE and review data distribution, predicates, and extended statistics where justified."))
        if loops >= 100:
            result.append(Bottleneck("high_loop_count", "high", {"actual_loops": loops}, n.node_id,
                "A high loop count amplifies the work performed by this plan node.",
                "Investigate join order, cardinality estimates, and indexes supporting the repeated operation."))
        if n.rows_removed_by_filter > max(actual or 0, 1) * 2:
            result.append(Bottleneck("filtering_inefficiency", "medium", {"rows_removed_by_filter": n.rows_removed_by_filter, "actual_rows": actual}, n.node_id,
                "The node discarded substantially more rows than it returned, indicating filtering occurs after significant row production.",
                "Review predicate selectivity and whether an index or earlier filtering can reduce rows processed."))
    return _dedupe(result)


def _dedupe(items: list[Bottleneck]) -> list[Bottleneck]:
    seen: set[tuple[str, str]] = set()
    out = []
    for item in items:
        key = (item.type, item.affected_node)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
