from __future__ import annotations

from app.services.plans.models import PlanFeatureVector, PlanGraph


def _depth(graph: PlanGraph, node_id: str, memo: dict[str, int]) -> int:
    if node_id in memo:
        return memo[node_id]
    children = graph.nodes[node_id].children
    value = 1 + max((_depth(graph, c, memo) for c in children), default=0)
    memo[node_id] = value
    return value


def extract_features(graph: PlanGraph) -> PlanFeatureVector:
    nodes = list(graph.nodes.values())
    counts = lambda names: sum(1 for n in nodes if n.node_type in names)
    row_errors = 0
    high_loops = 0
    expensive = 0
    filters = 0
    total_actual = 0.0
    for n in nodes:
        if n.actual_total_time_ms is not None:
            total_actual += n.actual_total_time_ms * max(n.actual_loops or 1, 1)
            if n.total_cost > 0 and n.actual_total_time_ms > 0:
                expensive += int(n.actual_total_time_ms >= max(10.0, total_actual * 0.20))
        if n.actual_rows is not None and n.plan_rows > 0:
            ratio = max(n.actual_rows, 0.001) / n.plan_rows
            if ratio >= 10 or ratio <= 0.1:
                row_errors += 1
        if (n.actual_loops or 0) >= 100:
            high_loops += 1
        if n.rows_removed_by_filter > max(n.actual_rows or 0, 1) * 2:
            filters += 1
    seq_scans_count = counts({"Seq Scan", "Parallel Seq Scan"})
    root_node = graph.nodes.get(graph.root_id)
    total_rows = int(root_node.plan_rows) if root_node else int(sum(n.plan_rows for n in nodes))
    return PlanFeatureVector(
        node_count=len(nodes),
        total_cost=sum(n.total_cost for n in nodes),
        total_actual_time_ms=total_actual,
        max_depth=_depth(graph, graph.root_id, {}),
        seq_scans=seq_scans_count,
        index_scans=counts({"Index Scan", "Index Only Scan", "Parallel Index Scan"}),
        bitmap_scans=counts({"Bitmap Heap Scan", "Bitmap Index Scan"}),
        nested_loops=counts({"Nested Loop", "Nested Loop Left Join", "Nested Loop Semi Join", "Nested Loop Anti Join"}),
        hash_joins=counts({"Hash Join", "Parallel Hash Join"}),
        merge_joins=counts({"Merge Join"}),
        sorts=counts({"Sort", "Incremental Sort"}),
        aggregates=counts({"Aggregate", "GroupAggregate", "HashAggregate", "MixedAggregate", "Partial Aggregate", "Finalize Aggregate"}),
        parallel_nodes=sum(1 for n in nodes if n.parallel_aware or n.workers_planned or n.workers_launched),
        row_estimation_errors=row_errors,
        high_loop_nodes=high_loops,
        expensive_nodes=expensive,
        filtering_inefficiencies=filters,
        total_rows=total_rows,
        seq_scan_fraction=round(seq_scans_count / max(1, len(nodes)), 4),
    )
