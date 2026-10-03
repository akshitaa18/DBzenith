from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GraphSample:
    graph_id: str
    node_features: list[list[float]]
    edge_index: list[list[int]]
    edge_features: list[list[float]]
    node_labels: list[int]
    node_ids: list[str]
    metadata: dict[str, Any]


LABELS = (
    "none",
    "sequential_scan",
    "nested_loop",
    "expensive_sort",
    "row_estimation_error",
)
LABEL_TO_ID = {name: i for i, name in enumerate(LABELS)}
ID_TO_LABEL = {i: name for name, i in LABEL_TO_ID.items()}
