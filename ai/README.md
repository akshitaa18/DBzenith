# DBZenith AI Subsystems

DBZenith incorporates learned intelligence while strictly preserving database privacy and production safety.

## 1. Graph Neural Network (GNN) Bottleneck Prediction (v0.7)
* Predicts execution plan bottlenecks using PyTorch / PyTorch Geometric on sanitized `PlanGraph` models.
* Raw queries, plan literals, and user data are strictly excluded.
* Artifacts: `ai/gnn/models/v0.7.0/`

## 2. Reinforcement Learning Optimization Engine (v0.8)
* Autonomous workload optimization via Gymnasium-compatible environment (`DatabaseOptimizationEnv`).
* Action space: `NO_OP`, `CREATE_INDEX`, `DROP_INDEX`, `REWRITE_QUERY`, `PARTITION_TABLE`, `CHANGE_JOIN_STRATEGY`.
* Strict safety pipeline: **`RL -> recommendation -> sandbox -> measured result -> reward`**.
* The RL agent is strictly prohibited from mutating production databases.
* Multi-objective reward balancing latency, throughput, storage, write overhead, CPU load, regressions, and risk.
* Artifacts: `ai/rl/models/v0.8.0/`
* Documentation: `docs/RL.md`
