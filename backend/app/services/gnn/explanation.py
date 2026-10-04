from __future__ import annotations

from typing import Any


def explain_predictions(predictions: list[dict[str, Any]], graph: Any) -> dict[str, Any]:
    """Converts GNN node classification predictions into structural evidence and human-readable explanations.
    
    Architecture:
    Execution Plan -> Graph Construction -> GNN (Node Classification) -> Evidence Extraction -> Explanation Layer
    """
    node_diagnoses = []
    flagged_bottlenecks = []

    for pred, node_id in zip(predictions, graph.nodes):
        label = pred["label"]
        conf = float(pred["confidence"])
        node = graph.nodes[node_id]

        evidence_items: list[str] = []
        interpretation: str = ""
        remediation: str = ""

        # Extract real structural graph evidence (no synthetic/invented numbers)
        rel_str = f"'{node.relation}'" if node.relation else "target relation"
        cost_val = round(float(node.total_cost), 1)
        rows_val = round(float(node.plan_rows), 1)
        loops_val = round(float(node.actual_loops), 1) if node.actual_loops is not None else None
        time_val = round(float(node.actual_total_time_ms), 2) if node.actual_total_time_ms is not None else None

        if label == "sequential_scan":
            evidence_items.append(f"Scan operator '{node.node_type}' dominates execution cost with total estimated cost of {cost_val}")
            evidence_items.append(f"Estimated cardinality reads {rows_val:,.0f} rows sequentially from relation {rel_str}")
            if node.rows_removed_by_filter and node.rows_removed_by_filter > 0:
                evidence_items.append(f"Filtered out {round(node.rows_removed_by_filter):,.0f} tuples during heap scan due to unindexed predicate")
            if loops_val and loops_val > 1:
                evidence_items.append(f"Repeated execution across {loops_val:,.0f} loops amplifies sequential scan overhead")
            interpretation = (
                f"The PostgreSQL query planner is performing a full relation scan on {rel_str} instead of utilizing "
                f"a selective index access path. This becomes increasingly expensive as table volume scales."
            )
            remediation = f"Add a composite or B-Tree index on the selective filter/join columns of {rel_str}."

        elif label == "nested_loop":
            evidence_items.append(f"Nested loop join node executed with loop multiplier = {loops_val or 1:,.0f}")
            evidence_items.append(f"Inner plan branch evaluated repeatedly for each qualifying outer tuple (cost: {cost_val})")
            interpretation = (
                "The outer relation produces multiple candidate tuples, causing the inner branch to execute repeatedly. "
                "Without selective index coverage on the join condition, this leads to quadratic latency amplification."
            )
            remediation = "Add an index on the inner relation's join attributes or evaluate switching planner join strategy to Hash Join."

        elif label == "expensive_sort":
            evidence_items.append(f"Explicit sort operator required {time_val or 0:.2f} ms execution time")
            evidence_items.append(f"Sorting volume of {rows_val:,.0f} tuples with estimated cost {cost_val}")
            interpretation = (
                "The query requires an explicit sort operation before projecting or returning rows. Lack of index-ordered "
                "retrieval causes disk/memory sort overhead."
            )
            remediation = "Evaluate adding an index matching the ORDER BY column specification, or tune work_mem to prevent disk spills."

        elif label == "row_estimation_error":
            actual_r = node.actual_rows or 0.0
            evidence_items.append(f"Planner estimated {rows_val:,.0f} rows vs actual observed {actual_r:,.0f} rows")
            ratio = (actual_r + 0.001) / (rows_val + 0.001)
            evidence_items.append(f"Estimation divergence factor: {ratio:.1f}x")
            interpretation = (
                "Severe discrepancy between planner statistics and actual table row counts. Skewed statistics prevent "
                "the cost model from choosing optimal join order and access methods."
            )
            remediation = f"Run ANALYZE on {rel_str} and consider creating extended statistics on correlated columns."

        else:
            evidence_items.append("No critical bottleneck detected on this operator node")
            interpretation = "Operator execution parameters fall within expected cost and selectivity bounds."
            remediation = "No remedial index or rewrite necessary for this operator."

        diagnosis = {
            "node_id": node_id,
            "node_type": node.node_type,
            "relation": node.relation,
            "prediction": label,
            "confidence": conf,
            "probabilities": pred.get("probabilities", {}),
            "evidence": evidence_items,
            "interpretation": interpretation,
            "recommended_optimization": remediation,
            "graph_evidence": {
                "node_type": node.node_type,
                "relation": node.relation or "N/A",
                "estimated_cost": cost_val,
                "estimated_rows": rows_val,
                "actual_rows": node.actual_rows,
                "actual_time_ms": time_val,
                "loop_count": loops_val or 1,
            },
        }
        node_diagnoses.append(diagnosis)
        if label != "none":
            flagged_bottlenecks.append(diagnosis)

    # Sort flagged bottlenecks by confidence * cost impact
    flagged_bottlenecks.sort(
        key=lambda x: (x["confidence"], x["graph_evidence"]["estimated_cost"]),
        reverse=True,
    )

    # Generate synthesis summary
    if flagged_bottlenecks:
        top = flagged_bottlenecks[0]
        summary = (
            f"GNN classified '{top['prediction'].replace('_', ' ')}' on {top['relation'] or top['node_type']} "
            f"(confidence: {top['confidence']:.0%}) as the dominant bottleneck in the execution graph. "
            f"{top['interpretation']}"
        )
    else:
        summary = "GNN evaluated the graph topology and classified all relational operators within normal execution parameters."

    return {
        "summary": summary,
        "flagged_bottlenecks": flagged_bottlenecks,
        "node_predictions": node_diagnoses,
        "architecture_flow": [
            {"stage": 1, "name": "Execution Plan", "detail": "PostgreSQL EXPLAIN plan extracted without raw customer data"},
            {"stage": 2, "name": "Privacy Gateway", "detail": "Mandatory parameter sanitization (raw-data exposure = 0)"},
            {"stage": 3, "name": "Graph Construction", "detail": "Operators parsed into directed plan graph nodes and edges"},
            {"stage": 4, "name": "GNN Inference", "detail": "Graph Neural Network classifies structural bottleneck patterns"},
            {"stage": 5, "name": "Evidence Extraction", "detail": "Deterministic extraction of cardinalities, costs, and loop counts"},
            {"stage": 6, "name": "Explanation Layer", "detail": "Translates structural predictions and evidence into DBA actionable recommendations"},
        ],
    }

