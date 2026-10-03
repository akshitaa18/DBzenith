from __future__ import annotations

from typing import Any

from app.services.plans.models import PlanGraph, PlanNode


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_plan(plan: dict[str, Any] | list[Any]) -> PlanGraph:
    root = plan
    if isinstance(root, list):
        if not root or not isinstance(root[0], dict):
            raise ValueError("EXPLAIN JSON must contain a plan object")
        root = root[0]
    if "Plan" in root:
        root = root["Plan"]
    if not isinstance(root, dict) or "Node Type" not in root:
        raise ValueError("invalid PostgreSQL EXPLAIN plan")

    nodes: dict[str, PlanNode] = {}
    edges: list[tuple[str, str]] = []

    def visit(raw: dict[str, Any], parent: str | None, depth: int) -> str:
        node_id = f"n{len(nodes) + 1}"
        node = PlanNode(
            node_id=node_id,
            node_type=str(raw.get("Node Type", "Unknown")),
            relation=raw.get("Relation Name"),
            index_name=raw.get("Index Name"),
            parent_relationship=raw.get("Parent Relationship"),
            startup_cost=_number(raw.get("Startup Cost")),
            total_cost=_number(raw.get("Total Cost")),
            plan_rows=_number(raw.get("Plan Rows")),
            actual_rows=_number(raw.get("Actual Rows"), 0.0) if "Actual Rows" in raw else None,
            actual_loops=_number(raw.get("Actual Loops"), 0.0) if "Actual Loops" in raw else None,
            actual_total_time_ms=_number(raw.get("Actual Total Time"), 0.0) if "Actual Total Time" in raw else None,
            actual_startup_time_ms=_number(raw.get("Actual Startup Time"), 0.0) if "Actual Startup Time" in raw else None,
            rows_removed_by_filter=_number(raw.get("Rows Removed by Filter")),
            parallel_aware=bool(raw.get("Parallel Aware", False)),
            workers_planned=int(_number(raw.get("Workers Planned"))),
            workers_launched=int(_number(raw.get("Workers Launched"))),
            filter=raw.get("Filter"),
            properties={k: v for k, v in raw.items() if k not in {"Plans", "Node Type", "Relation Name", "Index Name", "Actual Rows", "Actual Loops", "Actual Total Time", "Actual Startup Time", "Plan Rows", "Startup Cost", "Total Cost"}},
        )
        nodes[node_id] = node
        if parent:
            edges.append((parent, node_id))
            nodes[parent].children.append(node_id)
        for child in raw.get("Plans", []) or []:
            if isinstance(child, dict):
                visit(child, node_id, depth + 1)
        return node_id

    root_id = visit(root, None, 0)
    return PlanGraph(root_id=root_id, nodes=nodes, edges=edges)
