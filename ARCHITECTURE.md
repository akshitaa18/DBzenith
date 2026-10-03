# DBZenith System Architecture

## Runtime Architecture

DBZenith is organized into five isolated architectural tiers:

```text
[ Browser Client ]
       │
       ▼
[ Presentation Tier ]  React 18 + TypeScript + Vite Dashboard (11 Technical DBA Views)
       │
       ▼ HTTP / REST
[ Gateway & Security ] FastAPI Router + RBAC + HMAC Security + Rate Limiter + Audit Recorder
       │
       ├───────────────────────────────────────┐
       ▼                                       ▼
[ Core Observability ]                 [ Advisory & AI Engines ]
  • Telemetry Worker                     • GNN Plan Cost Surrogate
  • Sliding-Window Collector             • Gymnasium RL Optimization Environment
  • pg_stat_statements Reader            • DQN Trainable Policy & Baseline
  • PostgreSQL System Catalogs           • AST SQL Rewriter with Semantic Check
       │                                 • LangGraph Conversational DBA Assistant
       ▼                                       │
[ Privacy Gateway Boundary ] ◄─────────────────┘
  • Lexer & AST Parser
  • Constant & Literal Masker
  • Deterministic Identifier Tokenizer
  • Structural Plan Hasher
  • Privacy Policy Engine (Zero Raw Data to AI)
       │
       ▼
[ Experimentation & Execution ]
  • Isolated Sandbox Database (HypoPG Extension)
  • Ephemeral Replication Engine
  • Benchmark Difference Calculator
  • Human-in-the-Loop Approval Center
  • Production PostgreSQL Engine (Read-Only Observation)
```

---

## Subsystem Details

### 1. Telemetry Subsystem (`backend/app/services/collector`)
- Continuous background worker reading PostgreSQL `pg_stat_statements` and table statistics.
- Cross-version compatibility: dynamically inspects catalog columns, resolving block read/write metrics across PostgreSQL 13 through 17+.
- Persists structured `workload_snapshots` and `query_statistics` without storing raw user row data.

### 2. Privacy Gateway (`backend/app/services/privacy`)
- Acts as a mandatory firewall between database telemetry and machine learning models.
- Translates `RawQuery` into `SanitizedQuery` and `RawPlan` into `SanitizedPlan`.
- Replaces column and relation names with deterministic SHA-256 tokens (`id_<hash>`), ensuring isomorphic plan graphs retain topological properties without leaking business schemas.
- Scans and blocks credentials, connection strings, bearer tokens, and private keys.

### 3. Graph Neural Network (GNN) Surrogate (`backend/app/services/gnn`)
- Converts sanitized plan graphs into numerical node feature matrices and edge connectivity tensors.
- GCN-based surrogate cost model predicts operator execution bottlenecks and correlates plan shapes with empirical execution times.
- Fallback heuristic bottleneck detector guarantees advisory functionality even in minimal CPU or lightweight environments.

### 4. Reinforcement Learning Optimization Engine (`backend/app/services/rl`)
- Gymnasium-compatible environment (`DatabaseOptimizationEnv`) modeling database state transitions.
- Observation space: 38 normalized continuous features across 9 sanitized dimensions.
- Action space: 6 discrete actions (`NO_OP`, `CREATE_INDEX`, `DROP_INDEX`, `REWRITE_QUERY`, `PARTITION_TABLE`, `CHANGE_JOIN_STRATEGY`).
- Multi-objective reward function incorporating latency gains, throughput deltas, storage footprint penalties, write maintenance overhead, and regression risk.
- Trainable DQN policy with experience replay, target networks, and model persistence.

### 5. Safe SQL AST Rewriter (`backend/app/services/rewriter`)
- Transforms SQL ASTs using conservative rewrite rules (subquery unnesting, predicate pushdown, join reordering).
- Validates transformed queries inside the isolated sandbox, executing bounded result set comparisons to verify exact semantic equivalence before issuing recommendations.

### 6. Conversational DBA Assistant (`backend/app/services/assistant`)
- LangGraph state graph orchestrating 10 authorized controlled tools.
- Hard safety barriers: Prompt injection detector rejects jailbreak patterns; arbitrary SQL execution is strictly blocked; tool authorizer gates migration requests.

### 7. Isolated Sandbox (`backend/app/services/sandbox`)
- Runs in an isolated Docker container with the `hypopg` extension pre-installed.
- Replicates schemas and bounded rows to measure hypothetical index impact without creating physical indexes or taking locks on production tables.

### 8. Presentation Dashboard (`frontend/src`)
- 11 dedicated DBA views built in React and TypeScript:
  1. Overview
  2. Slow Queries
  3. Query Details
  4. Plan Viewer
  5. GNN Analysis
  6. Recommendations
  7. Simulations
  8. Approval Center
  9. DBA Assistant
  10. System Health
  11. Audit Logs
