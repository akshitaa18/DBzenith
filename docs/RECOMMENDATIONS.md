# DBZenith Optimization Recommendations

DBZenith v0.6 adds deterministic optimization advisors. This subsystem is deliberately rule-based; it does not claim machine-learning inference and does not implement GNN/RL.

## Advisors

- **IndexAdvisor**: inspects WHERE and JOIN predicates, ORDER BY and GROUP BY keys, existing PostgreSQL indexes, query frequency, execution cost, redundant coverage, and composite-index opportunities.
- **PartitionAdvisor**: identifies high-cost, frequent workloads with time-like range predicates as partitioning candidates.
- **QueryRewriteAdvisor**: flags expensive `SELECT *` and heavy temporary-block workloads for deterministic rewrite review.
- **JoinStrategyAdvisor**: uses real EXPLAIN JSON evidence to identify expensive/high-loop nested loops and expensive hash joins.

## Recommendation contract

Every persisted recommendation contains:

`ID`, `type`, `target`, `proposed_change`, `reason`, `evidence`, `expected_benefit`, `risk`, `confidence`, `affected_queries`, and `requires_approval`.

Recommendations start in `pending` state. Approval/rejection changes only the recommendation state and writes an audit event. **No recommendation endpoint executes DDL or modifies a production database.**

## APIs

- `GET /api/v1/recommendations`
- `GET /api/v1/recommendations/{id}`
- `POST /api/v1/recommendations/{id}/approve`
- `POST /api/v1/recommendations/{id}/reject`

The list endpoint deterministically derives recommendations from the persisted real PostgreSQL workload telemetry and catalogs, then idempotently persists them.
