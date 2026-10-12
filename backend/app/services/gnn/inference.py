from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .evaluation import RuleBasedNodeBaseline, run_comprehensive_gnn_evaluation
from .explanation import explain_predictions
from .graph import build_graph_sample
from .registry import (
    GNNArtifactMissingError,
    GNNInputValidationError,
    GNNRegistry,
    validate_graph_inputs,
)

logger = logging.getLogger(__name__)

_CACHED_EVAL_REPORT: dict[str, Any] | None = None
_CACHED_EVAL_DIR: str | None = None


def get_gnn_evaluation_report(model_dir: Path, *, force_recompute: bool = False) -> dict[str, Any]:
    """Load or compute the comprehensive GNN evaluation and transparency report."""
    global _CACHED_EVAL_REPORT, _CACHED_EVAL_DIR
    resolved_str = str(model_dir.resolve()) if model_dir.exists() else str(model_dir)
    if not force_recompute and _CACHED_EVAL_REPORT is not None and _CACHED_EVAL_DIR == resolved_str:
        return _CACHED_EVAL_REPORT

    report_path = model_dir / "evaluation_report.json"
    if not force_recompute and report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            _CACHED_EVAL_REPORT = report
            _CACHED_EVAL_DIR = resolved_str
            return report
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read cached GNN evaluation_report.json (%s); recomputing.", exc)

    report = run_comprehensive_gnn_evaluation(model_dir, persist_artifacts=model_dir.exists())
    _CACHED_EVAL_REPORT = report
    _CACHED_EVAL_DIR = resolved_str
    return report


def infer(
    graph: Any,
    model_dir: Path,
    *,
    allow_fallback: bool = True,
) -> dict[str, Any]:
    """Run GNN node bottleneck inference with input validation, deterministic fallback, and transparency."""
    if graph is None or not hasattr(graph, "nodes") or not isinstance(graph.nodes, dict):
        raise GNNInputValidationError("Invalid execution plan graph: expected a PlanGraph with a 'nodes' mapping.")
    if len(graph.nodes) == 0:
        raise GNNInputValidationError("Execution plan graph contains 0 operator nodes.")

    sample = build_graph_sample(graph)
    validate_graph_inputs(sample.node_features, sample.edge_index, sample.edge_features)

    is_fallback = False
    fallback_reason: str | None = None
    registry: GNNRegistry | None = None

    try:
        registry = GNNRegistry(model_dir)
        raw_predictions = registry.predict(sample.node_features, sample.edge_index, sample.edge_features)
        for pred in raw_predictions:
            pred["source_classification"] = "LEARNED_MODEL"
            pred["is_fallback"] = False
            pred["confidence_source"] = "learned_softmax_probability"
    except (GNNArtifactMissingError, FileNotFoundError) as exc:
        if not allow_fallback:
            raise
        is_fallback = True
        fallback_reason = str(exc)
        logger.warning("GNN artifact unavailable (%s); activating deterministic RuleBasedNodeBaseline fallback.", exc)
        baseline = RuleBasedNodeBaseline()
        raw_predictions = baseline.predict_graph(sample.node_features)

    explanations = explain_predictions(
        raw_predictions,
        graph,
        is_fallback=is_fallback,
        fallback_reason=fallback_reason,
    )

    eval_report: dict[str, Any] | None = None
    if not is_fallback and model_dir.exists():
        try:
            eval_report = get_gnn_evaluation_report(model_dir)
        except Exception as exc:
            logger.warning("Unable to load GNN evaluation report: %s", exc)

    model_version = (
        registry.version
        if registry is not None
        else f"{RuleBasedNodeBaseline.name}-{RuleBasedNodeBaseline.version}"
    )
    model_type = (
        "Deterministic Rule-Based Node Baseline (Fallback)"
        if is_fallback
        else (
            "GCN"
            if (registry and registry.metrics.get("pyg_available"))
            else "GCN-compatible message-passing fallback"
        )
    )
    source_classification = "DETERMINISTIC_FALLBACK" if is_fallback else "LEARNED_MODEL"

    transparency = {
        "model_name": (
            RuleBasedNodeBaseline.name
            if is_fallback
            else (eval_report.get("model_name") if eval_report else "BottleneckGNN")
        ),
        "model_version": model_version,
        "model_type": model_type,
        "source_classification": source_classification,
        "inference_mode": "deterministic_fallback" if is_fallback else "learned_gnn_artifact",
        "is_fallback": is_fallback,
        "fallback_reason": fallback_reason,
        "evaluation_dataset_type": (
            eval_report.get("dataset_type", "SYNTHETIC_AND_REPRESENTATIVE_HELD_OUT_PLANS")
            if eval_report
            else "SYNTHETIC_AND_REPRESENTATIVE_HELD_OUT_PLANS"
        ),
        "validated_on_real_workloads": False,
        "last_evaluation_time": (
            eval_report.get("evaluated_at")
            if eval_report
            else None
        ),
        "known_limitations": (
            eval_report.get("known_limitations")
            if eval_report
            else [
                "Not validated on live production customer workloads; metrics are derived from synthetic and representative query plan templates.",
                "Deterministic fallback does not produce neural probabilities (confidence is explicitly null when fallback is active).",
            ]
        ),
    }

    validation_metrics = (
        registry.metrics["gnn"]
        if registry is not None and "gnn" in registry.metrics
        else {
            "accuracy": (
                eval_report["held_out_workload_metrics"]["rule_based_baseline"]["accuracy"]
                if eval_report and "held_out_workload_metrics" in eval_report
                else None
            ),
            "macro_f1": (
                eval_report["held_out_workload_metrics"]["rule_based_baseline"]["macro_f1"]
                if eval_report and "held_out_workload_metrics" in eval_report
                else None
            ),
            "note": "Learned GNN artifact unavailable; deterministic rule-based fallback active.",
        }
    )

    return {
        "model_version": model_version,
        "model_type": model_type,
        "source_classification": source_classification,
        "inference_mode": transparency["inference_mode"],
        "is_fallback": is_fallback,
        "fallback_reason": fallback_reason,
        "validation_metrics": validation_metrics,
        "evaluation_summary": {
            "legacy_perfect_score_investigation": eval_report.get("legacy_perfect_score_investigation"),
            "grouped_leakage_audit": eval_report.get("grouped_leakage_audit"),
            "grouped_test_metrics": eval_report.get("grouped_test_metrics"),
            "held_out_workload_metrics": eval_report.get("held_out_workload_metrics"),
            "dataset_sizes": eval_report.get("dataset_sizes"),
            "reproducibility": eval_report.get("reproducibility"),
        }
        if eval_report
        else None,
        "transparency": transparency,
        "predictions": explanations["node_predictions"],
        "summary": explanations["summary"],
        "flagged_bottlenecks": explanations["flagged_bottlenecks"],
        "architecture_flow": explanations["architecture_flow"],
    }

