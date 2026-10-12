"""Phase 9 tests: GNN & RL evaluation, leakage detection, fallback reliability, safety boundary, and transparency."""

from __future__ import annotations

import json
import math
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.core.security import Role, get_security_manager
from app.main import app
from app.services.gnn.evaluation import (
    LABELS,
    RuleBasedNodeBaseline,
    audit_dataset_leakage,
    build_grouped_evaluation_splits,
    build_held_out_workload_samples,
    compute_classification_report,
    make_legacy_dataset,
    reproduce_metrics_from_predictions,
    run_comprehensive_gnn_evaluation,
)
from app.services.gnn.inference import get_gnn_evaluation_report, infer
from app.services.gnn.registry import (
    GNNArtifactMissingError,
    GNNInputValidationError,
    validate_graph_inputs,
)
from app.services.gnn.train import synthetic_graph
from app.services.plans.models import PlanGraph, PlanNode
from app.services.rl.baseline import BaselinePolicy, NoChangePolicy, RandomPolicy
from app.services.rl.contracts import (
    ActionType,
    ExistingIndexes,
    PlanFeatures,
    QueryPerformance,
    RecommendationHistory,
    RegressionSignals,
    RLRecommendation,
    SandboxResults,
    SanitizedState,
    StorageImpact,
)
from app.services.rl.environment import (
    DatabaseOptimizationEnv,
    ProductionMutationForbiddenError,
)
from app.services.rl.evaluate import (
    audit_rl_training_artifacts,
    compare_policies,
    evaluate_policies_on_diverse_workload,
    is_action_valid_for_state,
    reproduce_rl_metrics_from_predictions,
    run_comprehensive_rl_evaluation,
)
from app.services.rl.inference import (
    RLInferenceService,
    RLInputValidationError,
    get_rl_evaluation_report,
    validate_rl_state,
)
from app.services.rl.persistence import DEFAULT_ARTIFACT_DIR, RLArtifactMissingError


GNN_ARTIFACT_DIR = Path("backend/app/services/gnn/model_artifacts/v0.7.0")
RL_ARTIFACT_DIR = DEFAULT_ARTIFACT_DIR


# ============================================================================
# Part A: GNN Evaluation, Leakage Detection & Reproducibility from Predictions
# ============================================================================


def test_gnn_legacy_perfect_score_leakage_detected():
    """Investigates and proves why the legacy 250-sample synthetic dataset reported 1.0 accuracy."""
    legacy_samples = make_legacy_dataset(250)
    train_split = legacy_samples[:200]
    val_split = legacy_samples[200:]

    audit = audit_dataset_leakage(train_split, val_split)
    assert audit["test_node_count"] == 80
    # 30 out of 80 validation nodes (37.5%) are byte-for-byte identical child nodes from training
    assert audit["exact_duplicate_node_count"] == 30
    assert audit["exact_duplicate_node_fraction"] == pytest.approx(0.375, abs=1e-4)
    # 100% of structural graph topologies overlap between train and validation
    assert audit["topology_overlap_fraction"] == 1.0
    assert audit["leakage_detected"] is True
    assert audit["deterministic_shortcut_analysis"]["has_deterministic_1to1_operator_shortcut"] is True


def test_gnn_grouped_splits_prevent_leakage_and_detect_injected_overlap():
    """Verifies grouped train/val/test splits have zero group overlap and that injected overlap is caught."""
    splits = build_grouped_evaluation_splits(samples_per_family=24, seed=202609)
    train_s = splits["train"]
    val_s = splits["validation"]
    test_s = splits["test"]

    train_groups = {s.metadata["template_group"] for s in train_s}
    val_groups = {s.metadata["template_group"] for s in val_s}
    test_groups = {s.metadata["template_group"] for s in test_s}

    assert train_groups.isdisjoint(val_groups)
    assert train_groups.isdisjoint(test_groups)
    assert val_groups.isdisjoint(test_groups)

    clean_audit = audit_dataset_leakage(train_s, test_s)
    assert clean_audit["group_id_overlap_count"] == 0
    assert clean_audit["exact_duplicate_graph_count"] == 0
    assert clean_audit["deterministic_shortcut_analysis"]["has_deterministic_1to1_operator_shortcut"] is False

    # Inject a training graph into the test split and verify audit_dataset_leakage flags it
    contaminated_test = list(test_s) + [train_s[0]]
    contaminated_audit = audit_dataset_leakage(train_s, contaminated_test)
    assert contaminated_audit["group_id_overlap_count"] >= 1
    assert contaminated_audit["exact_duplicate_graph_count"] >= 1
    assert contaminated_audit["leakage_detected"] is True


def test_gnn_reproduce_evaluation_metrics_from_saved_predictions():
    """Reproduces accuracy, per-class precision/recall/F1, and confusion matrix from saved predictions."""
    report = run_comprehensive_gnn_evaluation(GNN_ARTIFACT_DIR, persist_artifacts=True)
    predictions_path = GNN_ARTIFACT_DIR / "held_out_predictions.json"
    assert predictions_path.exists()

    saved_records = json.loads(predictions_path.read_text(encoding="utf-8"))
    assert len(saved_records) > 0

    reproduced = reproduce_metrics_from_predictions(saved_records)
    reported_gnn = report["grouped_test_metrics"]["gnn"]

    assert reproduced["accuracy"] == reported_gnn["accuracy"]
    assert reproduced["macro_f1"] == reported_gnn["macro_f1"]
    assert reproduced["macro_precision"] == reported_gnn["macro_precision"]
    assert reproduced["macro_recall"] == reported_gnn["macro_recall"]
    assert reproduced["confusion_matrix"] == reported_gnn["confusion_matrix"]
    assert set(reproduced["per_class"].keys()) == set(LABELS)

    # Held-out representative workload plans must also be evaluated against rule-based baseline
    ho = report["held_out_workload_metrics"]
    assert ho["gnn"]["total_nodes"] >= 9
    assert ho["rule_based_baseline"]["total_nodes"] == ho["gnn"]["total_nodes"]
    assert report["validated_on_real_workloads"] is False


# ============================================================================
# Part B: RL Evaluation, Training Regression Audit & Reproducibility
# ============================================================================


def test_rl_training_regression_audit_and_policy_comparison():
    """Verifies the RL evaluation report explains the 303 training regressions and compares against baselines."""
    report = run_comprehensive_rl_evaluation(RL_ARTIFACT_DIR, persist_artifacts=True)
    assert report["validated_on_real_workloads"] is False

    audit = report["training_regression_investigation"]
    assert audit["artifact_found"] is True
    assert audit["recorded_total_regressions"] == 303
    assert audit["recorded_total_training_steps"] == 2221
    assert audit["recorded_action_counts"]["PARTITION_TABLE"] == 846
    assert len(audit["root_causes"]) >= 3

    # Verify comparison includes TrainableRLAgent, BaselinePolicy, NoChangePolicy, and RandomPolicy
    in_dist = report["held_out_in_distribution_comparison"]
    assert "rl_agent" in in_dist
    assert "baseline_policy" in in_dist
    assert "no_change_policy" in in_dist
    assert "random_policy" in in_dist
    assert in_dist["no_change_policy"]["action_distribution"]["NO_OP"] == in_dist["no_change_policy"]["total_actions"]
    assert in_dist["no_change_policy"]["regression_frequency_pct"] == 0.0

    # Verify diverse multi-regime evaluation exposes raw DQN OOD regressions vs safety-gated 0% regressions
    diverse = report["diverse_multi_regime_evaluation"]["policy_summaries"]
    assert diverse["raw_dqn_agent"]["valid_action_rate_pct"] < 100.0
    assert diverse["raw_dqn_agent"]["regression_frequency_pct"] > 0.0
    assert diverse["safety_gated_dqn_agent"]["valid_action_rate_pct"] == 100.0
    assert diverse["safety_gated_dqn_agent"]["regression_frequency_pct"] == 0.0
    assert diverse["rule_based_baseline"]["valid_action_rate_pct"] == 100.0
    assert diverse["no_op_baseline"]["regression_frequency_pct"] == 0.0


def test_rl_reproduce_metrics_from_saved_predictions():
    """Reproduces RL evaluation metrics directly from held_out_predictions.json."""
    report = get_rl_evaluation_report(RL_ARTIFACT_DIR)
    preds_path = RL_ARTIFACT_DIR / "held_out_predictions.json"
    assert preds_path.exists()

    saved_by_policy = json.loads(preds_path.read_text(encoding="utf-8"))
    for policy_name, expected_summary in report["diverse_multi_regime_evaluation"]["policy_summaries"].items():
        records = saved_by_policy[policy_name]
        reproduced = reproduce_rl_metrics_from_predictions(records)
        assert reproduced["valid_action_rate_pct"] == expected_summary["valid_action_rate_pct"]
        assert reproduced["regression_frequency_pct"] == expected_summary["regression_frequency_pct"]
        assert reproduced["failure_rate_pct"] == expected_summary["failure_rate_pct"]
        assert reproduced["mean_reward"] == expected_summary["mean_reward"]
        assert reproduced["improvement_distribution"] == expected_summary["improvement_distribution"]


# ============================================================================
# Part C: Input Schema Validation, Missing Artifacts & Deterministic Fallback
# ============================================================================


def test_gnn_input_validation_rejects_corrupted_graphs():
    """Tests GNN input validation on empty graphs, wrong feature dims, NaN/Inf, and invalid edges."""
    # Empty graph
    empty_graph = PlanGraph(root_id="n1", nodes={}, edges=[])
    with pytest.raises(GNNInputValidationError, match="0 operator nodes"):
        infer(empty_graph, GNN_ARTIFACT_DIR)

    # Wrong feature dimension
    with pytest.raises(GNNInputValidationError, match="invalid feature length"):
        validate_graph_inputs([[0.1, 0.2, 0.3]], [], [])

    # NaN in node features
    bad_features = [[0.0] * 21]
    bad_features[0][3] = float("nan")
    with pytest.raises(GNNInputValidationError, match="non-finite"):
        validate_graph_inputs(bad_features, [], [])

    # Out-of-bounds edge index
    valid_features = [[0.0] * 21]
    with pytest.raises(GNNInputValidationError, match="out of bounds"):
        validate_graph_inputs(valid_features, [[0, 5]], [[1.0, 0.0, 0.0]])

    # Mismatched edge_features length
    two_nodes = [[0.0] * 21, [0.0] * 21]
    with pytest.raises(GNNInputValidationError, match="does not match edge_index count"):
        validate_graph_inputs(two_nodes, [[0, 1]], [])


def test_gnn_missing_artifact_uses_deterministic_fallback_without_fake_confidence(tmp_path: Path):
    """Verifies GNN inference falls back to RuleBasedNodeBaseline with confidence=None when artifacts are missing."""
    missing_dir = tmp_path / "nonexistent_gnn_v0"

    # Strict mode raises GNNArtifactMissingError
    with pytest.raises(GNNArtifactMissingError):
        infer(synthetic_graph(0), missing_dir, allow_fallback=False)

    # Default fallback mode uses deterministic rule baseline and never invents confidence
    fallback_res = infer(synthetic_graph(0), missing_dir, allow_fallback=True)
    assert fallback_res["is_fallback"] is True
    assert fallback_res["source_classification"] == "DETERMINISTIC_FALLBACK"
    assert fallback_res["inference_mode"] == "deterministic_fallback"
    assert fallback_res["transparency"]["validated_on_real_workloads"] is False
    assert fallback_res["transparency"]["is_fallback"] is True

    for pred in fallback_res["predictions"]:
        assert pred["confidence"] is None
        assert pred["probabilities"] is None
        assert pred["is_fallback"] is True
        assert pred["source_classification"] == "DETERMINISTIC_FALLBACK"
        assert pred["confidence_source"] == "none_deterministic_fallback"


def test_rl_input_validation_and_missing_artifact_fallback(tmp_path: Path):
    """Tests RL input validation on NaN/Inf, extra keys, SQL injection, OOD bounds, and missing artifacts."""
    # Extra unknown field rejected
    with pytest.raises(RLInputValidationError):
        validate_rl_state({"unknown_malicious_key": 123})

    # NaN float rejected
    with pytest.raises(RLInputValidationError, match="Non-finite"):
        validate_rl_state({"plan_features": {"total_plan_cost": float("nan")}})

    # Corrupted extreme cost rejected
    with pytest.raises(RLInputValidationError, match="Out-of-bounds total_plan_cost"):
        validate_rl_state({"plan_features": {"total_plan_cost": 1e12}})

    # SQL injection token inside state dict rejected
    with pytest.raises(RLInputValidationError, match="Unsafe raw SQL"):
        validate_rl_state({"plan_features": {"total_plan_cost": "DROP TABLE orders"}})

    # Missing artifact directory raises when allow_fallback=False
    missing_rl_dir = tmp_path / "missing_rl_v0"
    with pytest.raises(RLArtifactMissingError):
        RLInferenceService(model_dir=missing_rl_dir, allow_fallback=False)

    # Missing artifact directory falls back cleanly to BaselinePolicy with confidence=None
    fallback_service = RLInferenceService(model_dir=missing_rl_dir, allow_fallback=True)
    assert fallback_service.is_trained_agent_available is False
    res = fallback_service.optimize(SanitizedState())
    assert res["is_fallback"] is True
    assert res["policy_used"] == "baseline_heuristic"
    assert res["source_classification"] == "DETERMINISTIC_FALLBACK"
    assert res["confidence"] is None
    assert res["confidence_source"] == "none_deterministic_fallback"
    assert res["production_modified"] is False
    assert res["can_authorize_production"] is False


def test_rl_safety_gate_prevents_small_table_partition_regression():
    """Verifies that when raw DQN proposes PARTITION_TABLE on a small table (<= 300 MB), the safety gate intervenes."""
    from app.services.rl.contracts import WorkloadStatistics, WritePenalty

    service = RLInferenceService(model_dir=RL_ARTIFACT_DIR)
    assert service.is_trained_agent_available is True

    small_table_ood_state = SanitizedState(
        workload_statistics=WorkloadStatistics(total_calls=3800, mean_exec_time_ms=57.5, read_write_ratio=0.82),
        query_performance=QueryPerformance(p50_latency_ms=46.0, p95_latency_ms=115.0, slow_query_ratio=0.15),
        plan_features=PlanFeatures(total_plan_cost=680.0, seq_scan_fraction=0.22, index_scan_fraction=0.45, nested_loop_fraction=0.42),
        existing_indexes=ExistingIndexes(index_count=4, redundant_index_count=0, index_utilization_ratio=0.68),
        recommendation_history=RecommendationHistory(approved_count=5, rejected_count=0, pending_count=0, last_action_idx=4),
        sandbox_results=SandboxResults(last_improvement_pct=35.0, last_validation_status=1.0, last_speedup_factor=1.55, consecutive_sandbox_failures=0),
        storage_impact=StorageImpact(total_db_size_mb=240.0, storage_budget_utilization=0.20),
        write_penalty=WritePenalty(write_ops_per_minute=110.0, table_update_rate=0.18, write_overhead_score=0.20),
    )

    result = service.optimize(small_table_ood_state)
    assert result["raw_dqn_proposed_action"] == "PARTITION_TABLE"
    assert result["safety_gate_triggered"] is True
    assert result["action_type"] != "PARTITION_TABLE"
    assert result["sandbox_measured_result"]["regression_detected"] is False
    assert result["confidence"] is None
    assert result["source_classification"] == "DETERMINISTIC_FALLBACK"
    assert len(result["ood_warnings"]) >= 1


# ============================================================================
# Part D & E: Approval Boundary & API Transparency Endpoints
# ============================================================================


def test_approval_boundary_and_transparency_api_endpoints():
    """Verifies API endpoints expose evaluation/transparency metadata and enforce approval boundaries."""
    client = TestClient(app)
    viewer_token = get_security_manager().create_token("10", "viewer_u", Role.VIEWER)
    analyst_token = get_security_manager().create_token("11", "analyst_u", Role.ANALYST)
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
    analyst_headers = {"Authorization": f"Bearer {analyst_token}"}

    # 1. GNN evaluation endpoint
    gnn_eval_resp = client.get("/api/v1/plans/gnn/evaluation", headers=viewer_headers)
    assert gnn_eval_resp.status_code == 200
    gnn_eval = gnn_eval_resp.json()
    assert gnn_eval["model_name"] == "BottleneckGNN"
    assert gnn_eval["validated_on_real_workloads"] is False
    assert "grouped_test_metrics" in gnn_eval
    assert "legacy_perfect_score_investigation" in gnn_eval
    assert len(gnn_eval["known_limitations"]) >= 3

    # 2. RL evaluation endpoint
    rl_eval_resp = client.get("/api/v1/rl/evaluation", headers=viewer_headers)
    assert rl_eval_resp.status_code == 200
    rl_eval = rl_eval_resp.json()
    assert rl_eval["model_name"] == "DBZenith DQN Optimization Policy"
    assert rl_eval["validated_on_real_workloads"] is False
    assert "training_regression_investigation" in rl_eval
    assert "diverse_multi_regime_evaluation" in rl_eval

    # 3. RL optimize rejects invalid input with HTTP 422
    bad_resp = client.post(
        "/api/v1/rl/optimize",
        headers=analyst_headers,
        json={"workload_metrics": {"seq_scan_ratio": 2.5, "total_cost": -100}},
    )
    assert bad_resp.status_code == 422

    bad_extra_resp = client.post(
        "/api/v1/rl/optimize",
        headers=analyst_headers,
        json={"unrecognized_field": "DROP TABLE users"},
    )
    assert bad_extra_resp.status_code == 422

    # 4. Valid RL optimize response enforces approval boundary independent of model confidence
    opt_resp = client.post(
        "/api/v1/rl/optimize",
        headers=analyst_headers,
        json={"workload_metrics": {"seq_scan_ratio": 0.72, "total_cost": 850.0}},
    )
    assert opt_resp.status_code == 200
    opt_data = opt_resp.json()
    assert opt_data["production_modified"] is False
    assert opt_data["can_authorize_production"] is False
    assert opt_data["requires_human_approval"] is True
    assert opt_data["approval_independent_of_confidence"] is True
    assert opt_data["recommendation"]["requires_approval"] is True
    assert opt_data["transparency"]["validated_on_real_workloads"] is False

    # 5. Analyst cannot approve recommendations even if model confidence is high
    recs_resp = client.get("/api/v1/recommendations", headers=viewer_headers)
    if recs_resp.status_code == 200 and recs_resp.json().get("items"):
        rec_id = recs_resp.json()["items"][0]["id"]
        forbid_resp = client.post(
            f"/api/v1/recommendations/{rec_id}/approve",
            headers=analyst_headers,
            json={"reason": "High model confidence attempt"},
        )
        assert forbid_resp.status_code == 403
