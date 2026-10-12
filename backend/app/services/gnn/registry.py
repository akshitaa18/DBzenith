from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import torch

from .contracts import ID_TO_LABEL, LABELS, GraphSample
from .features import normalize
from .model import BottleneckGNN

EXPECTED_NODE_FEATURE_DIM = 21
EXPECTED_EDGE_FEATURE_DIM = 3
MAX_BOUNDED_GRAPH_NODES = 500
MAX_BOUNDED_GRAPH_EDGES = 2000


class GNNInputValidationError(ValueError):
    """Raised when GNN input graph schema, dimensions, or numerical values are invalid."""


class GNNArtifactMissingError(FileNotFoundError):
    """Raised when required GNN model artifacts are missing or corrupted."""


def validate_graph_inputs(
    node_features: list[list[float]],
    edge_index: list[list[int]],
    edge_features: list[list[float]] | None = None,
    expected_feature_dim: int = EXPECTED_NODE_FEATURE_DIM,
) -> None:
    """Validates node features, edge indices, and edge features before model inference."""
    if not isinstance(node_features, list) or len(node_features) == 0:
        raise GNNInputValidationError("Graph must contain at least 1 node feature vector.")
    if len(node_features) > MAX_BOUNDED_GRAPH_NODES:
        raise GNNInputValidationError(
            f"Graph node count ({len(node_features)}) exceeds bounded inference limit ({MAX_BOUNDED_GRAPH_NODES})."
        )

    num_nodes = len(node_features)
    for row_idx, row in enumerate(node_features):
        if not isinstance(row, (list, tuple)) or len(row) != expected_feature_dim:
            raise GNNInputValidationError(
                f"Node {row_idx} has invalid feature length {len(row) if isinstance(row, (list, tuple)) else 'non-list'}; "
                f"expected {expected_feature_dim}."
            )
        for col_idx, val in enumerate(row):
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise GNNInputValidationError(
                    f"Node {row_idx} feature[{col_idx}] must be numeric, got {type(val).__name__}."
                )
            fval = float(val)
            if math.isnan(fval) or math.isinf(fval):
                raise GNNInputValidationError(
                    f"Node {row_idx} feature[{col_idx}] contains non-finite value ({val})."
                )

    if not isinstance(edge_index, list):
        raise GNNInputValidationError("edge_index must be a list of [src, dst] pairs.")
    if len(edge_index) > MAX_BOUNDED_GRAPH_EDGES:
        raise GNNInputValidationError(
            f"Graph edge count ({len(edge_index)}) exceeds bounded inference limit ({MAX_BOUNDED_GRAPH_EDGES})."
        )

    for edge_i, pair in enumerate(edge_index):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise GNNInputValidationError(f"Edge {edge_i} must be a 2-element [src, dst] pair.")
        src, dst = pair[0], pair[1]
        if not isinstance(src, int) or not isinstance(dst, int) or isinstance(src, bool) or isinstance(dst, bool):
            raise GNNInputValidationError(f"Edge {edge_i} indices must be integers.")
        if src < 0 or src >= num_nodes or dst < 0 or dst >= num_nodes:
            raise GNNInputValidationError(
                f"Edge {edge_i} index [{src}, {dst}] out of bounds for {num_nodes} nodes."
            )

    if edge_features is not None and len(edge_index) > 0:
        if len(edge_features) != len(edge_index):
            raise GNNInputValidationError(
                f"edge_features count ({len(edge_features)}) does not match edge_index count ({len(edge_index)})."
            )
        for ef_i, ef_row in enumerate(edge_features):
            if not isinstance(ef_row, (list, tuple)) or len(ef_row) != EXPECTED_EDGE_FEATURE_DIM:
                raise GNNInputValidationError(
                    f"Edge feature {ef_i} has invalid length; expected {EXPECTED_EDGE_FEATURE_DIM}."
                )
            for v in ef_row:
                if not isinstance(v, (int, float)) or math.isnan(float(v)) or math.isinf(float(v)):
                    raise GNNInputValidationError(f"Edge feature {ef_i} contains non-finite value.")


class GNNRegistry:
    def __init__(self, model_dir: Path):
        self.model_dir = Path(model_dir)
        self.version = "v0.7.0-synth-20261003"

        metrics_path = self.model_dir / "metrics.json"
        normalizer_path = self.model_dir / "normalizer.json"
        weights_path = self.model_dir / "gnn.pt"

        missing = [p.name for p in (metrics_path, normalizer_path, weights_path) if not p.exists()]
        if missing:
            raise GNNArtifactMissingError(
                f"Missing required GNN model artifact(s) in {self.model_dir}: {', '.join(missing)}"
            )

        try:
            self.metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            self.normalizer = json.loads(normalizer_path.read_text(encoding="utf-8"))
            state_dict = torch.load(weights_path, map_location="cpu", weights_only=True)
        except Exception as exc:
            raise GNNArtifactMissingError(f"Failed to load GNN model artifacts from {self.model_dir}: {exc}") from exc

        feature_count = int(self.metrics.get("feature_count", EXPECTED_NODE_FEATURE_DIM))
        if len(self.normalizer.get("stats", [])) != feature_count:
            raise GNNArtifactMissingError(
                f"Normalizer feature count ({len(self.normalizer.get('stats', []))}) does not match metrics feature_count ({feature_count})."
            )

        has_self_lin = "conv1.self_lin.weight" in state_dict
        uses_pyg = False if has_self_lin else bool(self.metrics.get("pyg_available", False))
        self.model = BottleneckGNN(feature_count, 32, len(ID_TO_LABEL), uses_pyg=uses_pyg)
        self.model.load_state_dict(state_dict)
        self.model.eval()

    def predict(
        self,
        node_features: list[list[float]],
        edge_index: list[list[int]],
        edge_features: list[list[float]] | None = None,
    ) -> list[dict[str, Any]]:
        expected_dim = int(self.metrics.get("feature_count", EXPECTED_NODE_FEATURE_DIM))
        validate_graph_inputs(node_features, edge_index, edge_features, expected_feature_dim=expected_dim)

        x = torch.tensor(normalize(node_features, self.normalizer), dtype=torch.float32)
        edge = (
            torch.tensor(edge_index, dtype=torch.long).t().contiguous()
            if edge_index
            else torch.empty((2, 0), dtype=torch.long)
        )
        edge_attr = (
            torch.tensor(edge_features, dtype=torch.float32)
            if edge_features
            else torch.empty((0, EXPECTED_EDGE_FEATURE_DIM), dtype=torch.float32)
        )
        with torch.no_grad():
            logits = self.model(x, edge, edge_attr)
            probs = torch.softmax(logits, dim=1)

        outputs: list[dict[str, Any]] = []
        for p in probs:
            pred_idx = int(p.argmax().item())
            label = ID_TO_LABEL.get(pred_idx, "none")
            conf = float(p.max().item())
            if math.isnan(conf) or math.isinf(conf):
                raise GNNInputValidationError("Model produced non-finite probability output.")
            outputs.append(
                {
                    "label": label if label in LABELS else "none",
                    "confidence": round(conf, 4),
                    "confidence_source": "learned_gnn_softmax",
                    "is_fallback": False,
                    "probabilities": {ID_TO_LABEL[i]: round(float(v), 4) for i, v in enumerate(p)},
                }
            )
        return outputs
