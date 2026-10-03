from __future__ import annotations

from app.services.plans.detector import detect_bottlenecks
from app.services.plans.explanation import explain
from app.services.plans.features import extract_features
from app.services.plans.parser import parse_plan
from app.services.plans.sanitizer import sanitize_raw_plan
from app.services.privacy.contracts import RawPlan
from pathlib import Path

try:
    from app.services.gnn.inference import infer as gnn_infer
except Exception:  # optional ML dependency
    gnn_infer = None


def analyze_plan(raw_plan: RawPlan) -> dict:
    sanitized = sanitize_raw_plan(raw_plan)
    graph = parse_plan(sanitized.plan)
    features = extract_features(graph)
    bottlenecks = detect_bottlenecks(graph)
    explanation = explain(features, bottlenecks)
    learned = None
    model_dir = Path(__file__).resolve().parents[3] / "app" / "services" / "gnn" / "model_artifacts" / "v0.7.0"
    if gnn_infer is not None and (model_dir / "gnn.pt").exists():
        try:
            learned = gnn_infer(graph, model_dir)
        except Exception:
            learned = None
    return {
        "sanitized_plan": sanitized,
        "graph": {
            "root_id": graph.root_id,
            "nodes": [node.__dict__ for node in graph.nodes.values()],
            "edges": [{"from": a, "to": b} for a, b in graph.edges],
        },
        "features": features.__dict__,
        "bottlenecks": [b.__dict__ for b in bottlenecks],
        "explanation": explanation,
        "gnn": learned,
    }
