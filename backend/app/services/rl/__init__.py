"""DBZenith Reinforcement Learning Optimization Engine.

Includes:
- Gymnasium-compatible environment (`DatabaseOptimizationEnv`)
- Strict safety pipeline: RL -> recommendation -> sandbox -> measured result -> reward
- Production safety invariants (no production DDL)
- Trainable RL Agent (`TrainableRLAgent` / DQN)
- Baseline Policy (`BaselinePolicy`, `RandomPolicy`)
- Multi-objective reward calculator (`RewardCalculator`)
- Training and evaluation pipelines (`train_rl_agent`, `compare_policies`, `evaluate_policy`)
- Model persistence (`save_rl_artifacts`, `load_rl_artifacts`)
- Inference service (`RLInferenceService`)
"""

from app.services.rl.agent import QNetwork, ReplayBuffer, TrainableRLAgent
from app.services.rl.baseline import BaselinePolicy, RandomPolicy
from app.services.rl.contracts import (
    ActionType,
    ExistingIndexes,
    MeasuredSandboxResult,
    PlanFeatures,
    QueryPerformance,
    RecommendationHistory,
    RegressionSignals,
    RewardBreakdown,
    RLRecommendation,
    SandboxResults,
    SanitizedState,
    StorageImpact,
    WorkloadStatistics,
    WritePenalty,
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

__all__ = [
    "ActionType",
    "WorkloadStatistics",
    "QueryPerformance",
    "PlanFeatures",
    "ExistingIndexes",
    "RecommendationHistory",
    "SandboxResults",
    "StorageImpact",
    "WritePenalty",
    "RegressionSignals",
    "SanitizedState",
    "RLRecommendation",
    "MeasuredSandboxResult",
    "RewardBreakdown",
    "RewardCalculator",
    "DatabaseOptimizationEnv",
    "ProductionMutationForbiddenError",
    "BaselinePolicy",
    "RandomPolicy",
    "QNetwork",
    "ReplayBuffer",
    "TrainableRLAgent",
    "save_rl_artifacts",
    "load_rl_artifacts",
    "train_rl_agent",
    "evaluate_policy",
    "compare_policies",
    "RLInferenceService",
]
