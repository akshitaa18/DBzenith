"""Comprehensive unit and integration tests for the DBZenith RL Optimization Engine."""

import pytest
import numpy as np
import torch

from app.services.rl.agent import QNetwork, ReplayBuffer, TrainableRLAgent
from app.services.rl.baseline import BaselinePolicy, RandomPolicy
from app.services.rl.contracts import (
    ActionType,
    MeasuredSandboxResult,
    RewardBreakdown,
    RLRecommendation,
    SanitizedState,
)
from app.services.rl.environment import (
    DatabaseOptimizationEnv,
    ProductionMutationForbiddenError,
)
from app.services.rl.evaluate import compare_policies, evaluate_policy
from app.services.rl.inference import RLInferenceService
from app.services.rl.persistence import load_rl_artifacts, save_rl_artifacts
from app.services.rl.reward import RewardCalculator
from app.services.rl.train import train_rl_agent


def test_contracts_and_sanitized_state_categories():
    state = SanitizedState()
    # Verify all 9 required sanitized categories exist
    assert hasattr(state, "workload_statistics")
    assert hasattr(state, "query_performance")
    assert hasattr(state, "plan_features")
    assert hasattr(state, "existing_indexes")
    assert hasattr(state, "recommendation_history")
    assert hasattr(state, "sandbox_results")
    assert hasattr(state, "storage_impact")
    assert hasattr(state, "write_penalty")
    assert hasattr(state, "regression_signals")

    vec = state.to_vector()
    assert isinstance(vec, np.ndarray)
    assert vec.shape == (38,)
    assert not np.isnan(vec).any()
    assert not np.isinf(vec).any()


def test_action_types_defined():
    expected_actions = [
        "NO_OP",
        "CREATE_INDEX",
        "DROP_INDEX",
        "REWRITE_QUERY",
        "PARTITION_TABLE",
        "CHANGE_JOIN_STRATEGY",
    ]
    for name in expected_actions:
        action = ActionType.from_name(name)
        assert action.name == name
    assert len(ActionType) == 6


def test_gymnasium_environment_compliance():
    env = DatabaseOptimizationEnv(max_steps_per_episode=10, seed=42)
    assert env.action_space.n == 6
    assert env.observation_space.shape == (38,)

    obs, info = env.reset(seed=42)
    assert obs.shape == (38,)
    assert "production_modified" in info
    assert info["production_modified"] is False

    for action_idx in range(6):
        obs, reward, terminated, truncated, step_info = env.step(action_idx)
        assert obs.shape == (38,)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert step_info["production_modified"] is False
        assert "recommendation" in step_info
        assert "measured_result" in step_info
        assert "reward_breakdown" in step_info


def test_production_safety_invariant_enforced():
    env = DatabaseOptimizationEnv()
    # Malicious or direct mutation recommendation must be rejected
    dangerous_rec = RLRecommendation(
        action_type=ActionType.DROP_INDEX,
        action_name="DROP_INDEX",
        proposed_change="DROP DATABASE production;",
        reason="bad",
        expected_benefit_pct=0.0,
        risk_score=1.0,
        requires_approval=True,
    )
    with pytest.raises(ProductionMutationForbiddenError):
        env._assert_production_safety(dangerous_rec)

    # Actions that do not require approval must be rejected
    unapproved_rec = RLRecommendation(
        action_type=ActionType.CREATE_INDEX,
        action_name="CREATE_INDEX",
        proposed_change="CREATE INDEX idx ON t (a);",
        reason="auto",
        expected_benefit_pct=10.0,
        risk_score=0.1,
        requires_approval=False,
    )
    with pytest.raises(ProductionMutationForbiddenError):
        env._assert_production_safety(unapproved_rec)


def test_action_flow_rl_to_reward():
    env = DatabaseOptimizationEnv()
    obs, info = env.reset(seed=123)

    # Test CREATE_INDEX flow
    obs, reward, term, trunc, step_info = env.step(ActionType.CREATE_INDEX)
    rec = step_info["recommendation"]
    result = step_info["measured_result"]
    reward_bd = step_info["reward_breakdown"]

    assert rec["action_type"] == ActionType.CREATE_INDEX
    assert "CREATE INDEX" in rec["proposed_change"]
    assert "latency_improvement_pct" in result
    assert "storage_delta_mb" in result
    assert "write_overhead_score" in result
    assert "net_reward" in reward_bd
    assert reward == reward_bd["net_reward"]


def test_reward_function_properties():
    calc = RewardCalculator(w_latency=1.5, w_throughput=1.0, w_regression=2.5)

    # Positive outcome
    good_result = MeasuredSandboxResult(
        baseline_latency_ms=100.0,
        proposed_latency_ms=50.0,
        latency_improvement_pct=50.0,
        baseline_throughput_qps=10.0,
        proposed_throughput_qps=20.0,
        throughput_improvement_pct=100.0,
        storage_delta_mb=5.0,
        write_overhead_score=0.1,
        cpu_usage_delta_pct=-20.0,
        regression_detected=False,
        risk_score=0.1,
        sandbox_status="success",
    )
    good_bd = calc.compute(good_result)
    assert good_bd.net_reward > 0.0
    assert good_bd.regression_penalty == 0.0

    # Regressed outcome
    bad_result = MeasuredSandboxResult(
        baseline_latency_ms=100.0,
        proposed_latency_ms=150.0,
        latency_improvement_pct=-50.0,
        baseline_throughput_qps=10.0,
        proposed_throughput_qps=6.6,
        throughput_improvement_pct=-34.0,
        storage_delta_mb=25.0,
        write_overhead_score=0.8,
        cpu_usage_delta_pct=20.0,
        regression_detected=True,
        risk_score=0.9,
        sandbox_status="success",
    )
    bad_bd = calc.compute(bad_result)
    assert bad_bd.net_reward < 0.0
    assert bad_bd.regression_penalty > 0.0


def test_baseline_policy():
    policy = BaselinePolicy()

    # High sequential scan should trigger CREATE_INDEX
    state = SanitizedState(
        plan_features=SanitizedState().plan_features.model_copy(update={"seq_scan_fraction": 0.8}),
    )
    action = policy.select_action(state)
    assert action in (ActionType.CREATE_INDEX, ActionType.REWRITE_QUERY)

    # Regression signal should trigger NO_OP
    regressed_state = SanitizedState(
        regression_signals=SanitizedState().regression_signals.model_copy(update={"regression_detected": 1.0}),
    )
    assert policy.select_action(regressed_state) == ActionType.NO_OP


def test_trainable_rl_agent_and_learning_step():
    agent = TrainableRLAgent(state_dim=38, action_dim=6, buffer_capacity=1000, batch_size=16)
    state = np.random.randn(38).astype(np.float32)

    # Action selection
    action = agent.select_action(state, deterministic=True)
    assert isinstance(action, ActionType)

    # Populate buffer to enable training
    for _ in range(32):
        s = np.random.randn(38).astype(np.float32)
        s_next = np.random.randn(38).astype(np.float32)
        agent.replay_buffer.push(s, 1, 1.5, s_next, False)

    loss = agent.step_learning()
    assert loss is not None
    assert loss >= 0.0


def test_model_persistence(tmp_path):
    agent = TrainableRLAgent(state_dim=38, action_dim=6)
    metrics = {"mean_final_reward": 14.5}
    saved_dir = save_rl_artifacts(agent, directory=tmp_path, metrics=metrics)

    assert (tmp_path / "agent.pt").exists()
    assert (tmp_path / "config.json").exists()
    assert (tmp_path / "metrics.json").exists()

    loaded_agent, config = load_rl_artifacts(tmp_path)
    assert loaded_agent.state_dim == 38
    assert loaded_agent.action_dim == 6
    assert config["version"] == "v0.8.0"


def test_inference_service(tmp_path):
    agent = TrainableRLAgent(state_dim=38, action_dim=6)
    save_rl_artifacts(agent, directory=tmp_path)

    service = RLInferenceService(model_dir=tmp_path)
    assert service.is_trained_agent_available is True

    result = service.optimize(SanitizedState())
    assert "action_type" in result
    assert "recommendation" in result
    assert "sandbox_measured_result" in result
    assert "reward_breakdown" in result
    assert result["production_modified"] is False


def test_pipeline_training_and_comparison():
    env = DatabaseOptimizationEnv(max_steps_per_episode=5, seed=100)
    agent = TrainableRLAgent(state_dim=38, action_dim=6, batch_size=8)

    trained_agent, history = train_rl_agent(env=env, agent=agent, num_episodes=5, max_steps_per_episode=5, verbose=False)
    assert history["num_episodes"] == 5
    assert len(history["episode_rewards"]) == 5

    comparison = compare_policies(agent=trained_agent, num_episodes=3, seed_offset=500)
    assert "rl_agent" in comparison
    assert "baseline_policy" in comparison
    assert "markdown_table" in comparison


def test_rl_api_routes():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    status_resp = client.get("/api/v1/rl/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "ready"
    assert "actions_supported" in status_data

    optimize_resp = client.post("/api/v1/rl/optimize", json={})
    assert optimize_resp.status_code == 200
    optimize_data = optimize_resp.json()
    assert "action_type" in optimize_data
    assert "recommendation" in optimize_data
    assert "sandbox_measured_result" in optimize_data
    assert "reward_breakdown" in optimize_data
    assert optimize_data["production_modified"] is False
