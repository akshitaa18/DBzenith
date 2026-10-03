from pathlib import Path

from app.services.gnn.graph import build_graph_sample
from app.services.gnn.model import BaselineNodeClassifier, BottleneckGNN
from app.services.gnn.train import synthetic_graph


def test_synthetic_graph_is_sanitized_feature_only():
    sample = build_graph_sample(synthetic_graph(0), "test")
    assert sample.metadata["feature_source"] == "sanitized_plan"
    assert all("orders" not in str(row) for row in sample.node_features)
    assert len(sample.node_features[0]) == 21
    assert len(sample.edge_features[0]) == 3 if sample.edge_features else True


def test_gnn_and_baseline_forward():
    sample = build_graph_sample(synthetic_graph(1), "test")
    import torch
    x=torch.tensor(sample.node_features,dtype=torch.float32)
    e=torch.tensor(sample.edge_index,dtype=torch.long).t().contiguous()
    ea=torch.tensor(sample.edge_features,dtype=torch.float32)
    assert BaselineNodeClassifier(21,5)(x).shape == (len(sample.node_features),5)
    assert BottleneckGNN(21,16,5)(x,e,ea).shape == (len(sample.node_features),5)


def test_versioned_artifact_inference_uses_sanitized_graph():
    from app.services.gnn.inference import infer
    result = infer(synthetic_graph(0), Path("backend/app/services/gnn/model_artifacts/v0.7.0"))
    assert result["model_version"] == "v0.7.0-synth-20261003"
    assert result["validation_metrics"]["accuracy"] == 1.0
    assert result["predictions"][0]["prediction"] == "sequential_scan"
