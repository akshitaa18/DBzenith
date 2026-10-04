from __future__ import annotations

import json
from pathlib import Path

import torch

from .contracts import ID_TO_LABEL
from .features import normalize
from .model import BottleneckGNN


class GNNRegistry:
    def __init__(self, model_dir: Path):
        self.model_dir=model_dir
        self.version="v0.7.0-synth-20261003"
        self.metrics=json.loads((model_dir/"metrics.json").read_text())
        self.normalizer=json.loads((model_dir/"normalizer.json").read_text())
        state_dict = torch.load(model_dir / "gnn.pt", map_location="cpu")
        has_self_lin = "conv1.self_lin.weight" in state_dict
        uses_pyg = False if has_self_lin else bool(self.metrics.get("pyg_available", False))
        self.model = BottleneckGNN(self.metrics["feature_count"], 32, len(ID_TO_LABEL), uses_pyg=uses_pyg)
        self.model.load_state_dict(state_dict)
        self.model.eval()

    def predict(self, node_features, edge_index, edge_features=None):
        x=torch.tensor(normalize(node_features,self.normalizer),dtype=torch.float32)
        edge=torch.tensor(edge_index,dtype=torch.long).t().contiguous() if edge_index else torch.empty((2,0),dtype=torch.long)
        edge_attr=torch.tensor(edge_features,dtype=torch.float32) if edge_features else torch.empty((0,3),dtype=torch.float32)
        with torch.no_grad():
            probs=torch.softmax(self.model(x,edge,edge_attr),dim=1)
        return [{"label":ID_TO_LABEL[int(p.argmax())],"confidence":float(p.max()),"probabilities":{ID_TO_LABEL[i]:float(v) for i,v in enumerate(p)}} for p in probs]
