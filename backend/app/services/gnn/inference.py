from __future__ import annotations

from pathlib import Path

from .explanation import explain_predictions
from .graph import build_graph_sample
from .registry import GNNRegistry


def infer(graph, model_dir: Path):
    sample=build_graph_sample(graph)
    registry=GNNRegistry(model_dir)
    predictions=registry.predict(sample.node_features,sample.edge_index,sample.edge_features)
    explanations=explain_predictions(predictions,graph)
    return {"model_version":registry.version,"model_type":"GCN" if registry.metrics.get("pyg_available") else "GCN-compatible message-passing fallback","validation_metrics":registry.metrics["gnn"],"predictions":explanations}
