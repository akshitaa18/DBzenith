from __future__ import annotations

import math
from typing import Iterable


def _fit(values: Iterable[float]) -> tuple[float, float]:
    vals = [float(v) for v in values]
    mean = sum(vals) / max(len(vals), 1)
    var = sum((v - mean) ** 2 for v in vals) / max(len(vals), 1)
    return mean, math.sqrt(var) or 1.0


def fit_normalizer(samples) -> dict:
    width = len(samples[0].node_features[0])
    stats = []
    for j in range(width):
        mean, std = _fit(row[j] for sample in samples for row in sample.node_features)
        stats.append({"mean": mean, "std": std})
    return {"version": 1, "stats": stats}


def normalize(rows: list[list[float]], normalizer: dict) -> list[list[float]]:
    stats = normalizer["stats"]
    return [[(float(v) - stats[j]["mean"]) / stats[j]["std"] for j, v in enumerate(row)] for row in rows]
