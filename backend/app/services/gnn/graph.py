from __future__ import annotations

from app.services.plans.models import PlanGraph

from .contracts import LABEL_TO_ID, GraphSample


def _label(node) -> int:
    # Labels are generated from sanitized plan-derived signals only.
    if node.node_type in {"Seq Scan", "Parallel Seq Scan"} and node.relation:
        return LABEL_TO_ID["sequential_scan"]
    if node.node_type.startswith("Nested Loop") and (node.actual_loops or 0) >= 100:
        return LABEL_TO_ID["nested_loop"]
    if node.node_type in {"Sort", "Incremental Sort"} and (node.actual_total_time_ms or 0) >= 10:
        return LABEL_TO_ID["expensive_sort"]
    if node.plan_rows > 0 and node.actual_rows is not None:
        ratio = max(node.actual_rows, 0.001) / node.plan_rows
        if ratio >= 10 or ratio <= 0.1:
            return LABEL_TO_ID["row_estimation_error"]
    return LABEL_TO_ID["none"]


def build_graph_sample(graph: PlanGraph, graph_id: str = "inference") -> GraphSample:
    nodes = list(graph.nodes.values())
    index = {n.node_id: i for i, n in enumerate(nodes)}
    node_features: list[list[float]] = []
    labels: list[int] = []
    node_ids: list[str] = []
    for node in nodes:
        node_features.append([
            float(node.startup_cost),
            float(node.total_cost),
            float(node.plan_rows),
            float(node.actual_rows or 0),
            float(node.actual_loops or 0),
            float(node.actual_total_time_ms or 0),
            float(node.rows_removed_by_filter),
            float(node.parallel_aware),
            float(node.workers_planned),
            float(node.workers_launched),
            float(node.node_type in {"Seq Scan", "Parallel Seq Scan"}),
            float(node.node_type in {"Index Scan", "Index Only Scan", "Parallel Index Scan"}),
            float(node.node_type in {"Bitmap Heap Scan", "Bitmap Index Scan"}),
            float(node.node_type.startswith("Nested Loop")),
            float(node.node_type in {"Hash Join", "Parallel Hash Join"}),
            float(node.node_type == "Merge Join"),
            float(node.node_type in {"Sort", "Incremental Sort"}),
            float("Aggregate" in node.node_type),
            float(node.node_type == "Hash"),
            float(node.node_type == "Materialize"),
            float(node.index_name is not None),
        ])
        labels.append(_label(node))
        node_ids.append(node.node_id)
    edge_index = [[index[a], index[b]] for a, b in graph.edges]
    edge_features = []
    for a, b in graph.edges:
        parent = graph.nodes[a]
        child = graph.nodes[b]
        edge_features.append([
            1.0,
            float(parent.relation is not None and parent.relation == child.relation),
            float(child.index_name is not None),
        ])
    return GraphSample(graph_id, node_features, edge_index, edge_features, labels, node_ids, {"feature_source": "sanitized_plan"})
