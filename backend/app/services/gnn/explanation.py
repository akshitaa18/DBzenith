from __future__ import annotations


def explain_predictions(predictions, graph):
    out=[]
    for pred,node_id in zip(predictions, graph.nodes):
        label=pred["label"]
        node=graph.nodes[node_id]
        reasons=[]
        if label=="sequential_scan": reasons.append("sanitized plan identifies a sequential scan on a relation")
        if label=="nested_loop": reasons.append(f"sanitized loop count is {node.actual_loops or 0:.0f}")
        if label=="expensive_sort": reasons.append(f"sanitized sort time is {node.actual_total_time_ms or 0:.2f} ms")
        if label=="row_estimation_error": reasons.append(f"estimated rows={node.plan_rows:.2f}, actual rows={node.actual_rows or 0:.2f}")
        out.append({"node_id":node_id,"prediction":label,"confidence":pred["confidence"],"evidence":reasons or ["no learned bottleneck signal above fallback threshold"]})
    return out
