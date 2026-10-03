from __future__ import annotations

import torch
from torch import nn

try:
    from torch_geometric.nn import GCNConv
    HAS_PYG = True
except Exception:  # pragma: no cover - optional runtime fallback
    GCNConv = None
    HAS_PYG = False


class BaselineNodeClassifier(nn.Module):
    def __init__(self, in_features: int, classes: int):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(in_features, 32), nn.ReLU(), nn.Linear(32, classes))

    def forward(self, x, edge_index=None, edge_attr=None):
        return self.net(x)


class _MessageLayer(nn.Module):
    def __init__(self, in_features: int, out_features: int):
        super().__init__()
        self.self_lin = nn.Linear(in_features, out_features)
        self.neigh_lin = nn.Linear(in_features, out_features)

    def forward(self, x, edge_index, edge_attr=None):
        out = self.self_lin(x)
        if edge_index.numel():
            src, dst = edge_index
            msg = self.neigh_lin(x[src])
            agg = torch.zeros_like(out)
            agg.index_add_(0, dst, msg)
            deg = torch.zeros(x.size(0), device=x.device)
            deg.index_add_(0, dst, torch.ones_like(dst, dtype=x.dtype))
            out = out + agg / deg.clamp_min(1).unsqueeze(1)
        return out


class BottleneckGNN(nn.Module):
    """GCN when PyG is installed; equivalent message-passing fallback for constrained builds."""
    def __init__(self, in_features: int, hidden: int, classes: int):
        super().__init__()
        self.uses_pyg = HAS_PYG
        if HAS_PYG:
            self.conv1 = GCNConv(in_features, hidden)
            self.conv2 = GCNConv(hidden, hidden)
        else:
            self.conv1 = _MessageLayer(in_features, hidden)
            self.conv2 = _MessageLayer(hidden, hidden)
        self.head = nn.Linear(hidden, classes)

    def forward(self, x, edge_index, edge_attr=None):
        edge_weight = None
        if edge_attr is not None and edge_attr.numel():
            edge_weight = edge_attr[:, 0]
        x = torch.relu(self.conv1(x, edge_index, edge_weight) if self.uses_pyg else self.conv1(x, edge_index, edge_attr))
        x = torch.relu(self.conv2(x, edge_index, edge_weight) if self.uses_pyg else self.conv2(x, edge_index, edge_attr))
        return self.head(x)
