# DBZenith Architecture v0.6

## Purpose

DBZenith is a privacy-preserving platform for PostgreSQL workload analysis and controlled performance optimization.

## Runtime

```text
Browser
  |
  v
React + TypeScript + Vite
  |
  | HTTP / JSON
  v
FastAPI /api/v1
  |
  +--> health / readiness
  +--> telemetry APIs
  |
  +--> collector
  |      |
  |      +--> pg_stat_statements / catalogs / optional pg_qualstats
  |      +--> raw telemetry
  |             |
  |             v
  |      +-----------------------+
  |      | Privacy Gateway       |
  |      |                       |
  |      | SQL parser / AST      |
  |      | literal masking       |
  |      | identifier tokenizing |
  |      | structural hashing    |
  |      | plan sanitization     |
  |      | policy validation     |
  |      +-----------+-----------+
  |                  |
  |                  v
  |          AIWorkloadRecord
  |                  |
  |                  v
  |          AI-facing services
  |          (future only)
  |
  +--> SQLAlchemy --> PostgreSQL
  |
  +--> isolated sandbox --> Sandbox PostgreSQL
```

## Privacy Gateway

The privacy gateway is a mandatory boundary. Raw telemetry is an ingestion concern; AI consumption is a sanitized-contract concern.

### Contracts

| Contract | Allowed location | Purpose |
|---|---|---|
| `RawQuery` | collector/privacy ingress | carries raw SQL temporarily for sanitization |
| `SanitizedQuery` | privacy/AI boundary | literal-free structural SQL |
| `RawPlan` | collector/privacy ingress | raw PostgreSQL JSON plan temporarily for sanitization |
| `SanitizedPlan` | privacy/AI boundary | safe plan topology and metrics |
| `AIWorkloadRecord` | AI-facing modules | sole workload input contract for future AI |

### Boundary rules

1. SQL is parsed before AI handoff.
2. Comments and literals are removed/masked.
3. Identifiers are replaced by deterministic tokens.
4. Structural hashes are computed from the sanitized representation.
5. Execution-plan expressions are sanitized and unknown free-form plan text is redacted.
6. A policy engine validates the sanitized contracts.
7. The AI boundary accepts `AIWorkloadRecord` only.
8. Security audit events contain decisions and hashes, never raw payloads.
9. A failure is fail-closed.

## Service boundaries

| Service | Responsibility |
|---|---|
| collector | Pull PostgreSQL telemetry using native observability features. |
| privacy | Mandatory raw-to-sanitized gateway. |
| plans | Future plan analysis using sanitized plans. |
| recommendations | Future deterministic optimization candidates. |
| sandbox | Controlled PostgreSQL experiments. |
| gnn | Future graph learning; sanitized inputs only. |
| rl | Future bounded optimization search; sanitized inputs only. |
| agent | Future human-approved orchestration; sanitized inputs only. |

## Database separation

Normal development PostgreSQL and sandbox PostgreSQL remain separate containers, volumes, credentials, and networks. The sandbox network is internal.

## Human control

Any future production-changing operation must be represented as an explicit, auditable proposal and require human approval before execution. No LLM is permitted to execute arbitrary production SQL.

## v0.6 scope

Implemented: real PostgreSQL telemetry, persistence, query APIs, privacy contracts, SQL parsing/AST normalization, literal masking, structural hashing, identifier tokenization, execution-plan sanitization, privacy policy enforcement, AI boundary validation, and security audit logging.

Not implemented: GNN, reinforcement learning, LangGraph agents, autonomous production changes, or production migration execution.


## Execution-plan subsystem (v0.6)

PostgreSQL `EXPLAIN (FORMAT JSON)` plans enter through the privacy gateway before analysis or persistence. The plan subsystem consists of:

- `services/plans/parser.py`: PostgreSQL plan tree parser and graph construction.
- `services/plans/models.py`: plan node, graph, feature and bottleneck models.
- `services/plans/features.py`: scan/join/sort/aggregate/parallel/cardinality/loop/filter features.
- `services/plans/detector.py`: deterministic bottleneck rules.
- `services/plans/explanation.py`: human-readable structured explanations.
- `services/plans/sanitizer.py`: plan-specific privacy sanitization.

The persisted `plan_analyses` table contains only sanitized plan data. GNN/RL components remain placeholders.

## Optimization Recommendations

DBZenith v0.6 adds deterministic Index, Partition, Query Rewrite, and Join Strategy advisors. Recommendations are persisted, require explicit approval, and never execute production DDL. Approve/reject actions are audit logged. GNN/RL are not implemented.


## v0.6 simulation boundary

Optimization simulations execute only against the isolated sandbox PostgreSQL instance. HypoPG is installed in the sandbox only. Production tables are never modified by simulations. Sandbox DDL, benchmark indexes, and HypoPG state are cleaned after each run; timeouts, temp-file limits, row-copy caps, and benchmark limits constrain resource use.

### GNN subsystem

Sanitized plans are converted to graph samples with numeric node/edge features. A versioned GCN model produces advisory node-level bottleneck predictions and evidence-based explanations. No raw SQL literals or production row values cross this boundary. Deterministic detectors remain the fallback.
