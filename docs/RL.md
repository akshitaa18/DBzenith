# DBZenith Reinforcement Learning Optimization Engine

DBZenith v0.8 adds a safe, autonomous Reinforcement Learning (RL) optimization engine.

## Core Architectural Invariant

**The RL agent is strictly prohibited from mutating the production database directly.**

Every action must strictly flow through the pipeline:
```text
RL Action Selection
       │
       ▼
Optimization Recommendation Synthesis
       │
       ▼
Isolated Sandbox Simulation (HypoPG / Isolated Schema)
       │
       ▼
Measured Outcome & Plan Difference Extraction
       │
       ▼
Multi-Objective Reward Function
```

Production database modifications require explicit approval through the Recommendation and Audit subsystems.

---

## Gymnasium Environment (`DatabaseOptimizationEnv`)

`DatabaseOptimizationEnv` is a standard `gymnasium.Env` compliant environment.

### Observation Space

`Box(38,)` continuous normalized vector containing **9 sanitized categories**:

1. **Workload statistics**: `total_calls`, `mean_exec_time_ms`, `query_frequency_per_minute`, `read_write_ratio`, `active_connections`.
2. **Query performance**: `p50_latency_ms`, `p95_latency_ms`, `slow_query_ratio`, `buffer_hit_ratio`, `temp_blks_ratio`.
3. **Plan features**: `total_plan_cost`, `seq_scan_fraction`, `index_scan_fraction`, `nested_loop_fraction`, `hash_join_fraction`, `est_to_actual_row_ratio`.
4. **Existing indexes**: `index_count`, `total_index_size_mb`, `redundant_index_count`, `index_utilization_ratio`.
5. **Recommendation history**: `approved_count`, `rejected_count`, `pending_count`, `last_action_idx`.
6. **Sandbox results**: `last_improvement_pct`, `last_validation_status`, `last_speedup_factor`, `consecutive_sandbox_failures`.
7. **Storage impact**: `total_db_size_mb`, `estimated_new_index_size_mb`, `storage_budget_utilization`.
8. **Write penalty**: `write_ops_per_minute`, `table_update_rate`, `write_overhead_score`.
9. **Regression signals**: `regression_detected`, `latency_spike_ratio`, `buffer_spike_ratio`, `risk_level`.

### Action Space

`Discrete(6)` supporting six core database tuning primitives:

| ID | Action | Description |
|:---|:---|:---|
| `0` | `NO_OP` | Maintain status quo when workload is optimal or risk is unacceptable |
| `1` | `CREATE_INDEX` | Synthesize concurrent index recommendation on hot scan targets |
| `2` | `DROP_INDEX` | Recommend safe concurrent removal of verified redundant/unused index |
| `3` | `REWRITE_QUERY` | Recommend query rewrite (projection pruning, predicate pushdown) |
| `4` | `PARTITION_TABLE` | Propose range/list partitioning strategy for large tables |
| `5` | `CHANGE_JOIN_STRATEGY`| Recommend planner join strategy adjustments (e.g. hash over high-loop nested loop) |

---

## Multi-Objective Reward Function

The reward function balances query latency and throughput against physical storage, write overhead, CPU load, and plan regressions:

$$R = w_{\text{lat}} \cdot \Delta_{\text{latency}} + w_{\text{thr}} \cdot \Delta_{\text{throughput}} - w_{\text{stor}} \cdot \Delta_{\text{storage}} - w_{\text{write}} \cdot \text{write\_overhead} - w_{\text{cpu}} \cdot \text{cpu\_delta} - w_{\text{regress}} \cdot \mathbb{I}_{\text{regression}} - w_{\text{risk}} \cdot \text{risk}$$

* **Primary Optimization**: Latency reduction and throughput scaling.
* **Cost Penalties**: Index disk growth, index write/maintenance burden, CPU consumption.
* **Safety Penalties**: Heavy deterministic penalties for plan regressions or sandbox validation failures.

---

## Empirical Comparison: RL Agent vs Baseline

Evaluated over 50 held-out evaluation episodes (`scripts/evaluate_rl.py`):

| Metric | Trainable RL (DQN) | Baseline Policy (Heuristic) | Random Policy |
|:---|---:|---:|---:|
| **Mean Episode Return** | **+25.701** | +21.789 | -13.858 |
| **Mean Latency Impr. (%)** | **+27.10%** | +20.74% | +6.20% |
| **Mean Throughput Impr. (%)**| **+41.24%** | +28.90% | +16.42% |
| **Mean Storage Delta (MB)** | 2.94 MB | 0.55 MB | 2.12 MB |
| **Mean Write Overhead** | 0.137 | 0.007 | 0.067 |
| **Regression Rate (%)** | **0.00%** | **0.00%** | 26.24% |

### Key Findings
1. **Superior Return & Latency**: The DQN agent learned to outperform the heuristic baseline by identifying composite index and query rewrite synergies (+27.1% vs +20.74% latency improvement).
2. **Zero Regressions**: Under sandbox gating, the RL agent achieved a **0.0% regression rate**, matching the safety of conservative DBA heuristics while avoiding the catastrophic regressions seen in the unguided random policy (26.24%).

---

## Artifacts and Versioning

Model weights, configuration, and evaluation reports are versioned under `ai/rl/models/v0.8.0/`:
- `agent.pt`: PyTorch Q-Network state dict
- `config.json`: Hyperparameters and architecture definition
- `metrics.json`: Training history, loss, and return curves
- `comparison_report.json`: Held-out empirical evaluation benchmark results

---

## API & Inference Service

- `GET /api/v1/rl/status`: Returns model readiness and action vocabulary.
- `POST /api/v1/rl/optimize`: Dispatches sanitized state, selects RL action, runs sandbox simulation, and returns validated recommendations with multi-objective reward breakdowns.
