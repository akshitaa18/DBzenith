from __future__ import annotations

from app.services.plans.models import Bottleneck, PlanFeatureVector


def explain(features: PlanFeatureVector, bottlenecks: list[Bottleneck]) -> dict:
    if not bottlenecks:
        summary = "No major rule-based bottlenecks were detected in the supplied execution plan."
    else:
        summary = f"Detected {len(bottlenecks)} plan bottleneck(s), based on observed execution evidence and planner estimates."
    return {
        "summary": summary,
        "feature_highlights": {
            "node_count": features.node_count,
            "max_depth": features.max_depth,
            "total_cost": features.total_cost,
            "total_actual_time_ms": features.total_actual_time_ms,
            "parallel_nodes": features.parallel_nodes,
        },
        "method": "deterministic PostgreSQL execution-plan rules; no GNN/RL/AI inference",
    }
