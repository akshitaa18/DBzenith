# DBZenith Architecture v0.1

## Purpose

DBZenith is a privacy-preserving platform for PostgreSQL workload analysis and controlled performance optimization.

## v0.1 runtime

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
  |
  +--> service boundaries
  |      collector
  |      privacy
  |      plans
  |      recommendations
  |      sandbox
  |      gnn
  |      rl
  |      agent
  |
  +--> SQLAlchemy
          |
          v
      PostgreSQL

FastAPI --> isolated sandbox network --> Sandbox PostgreSQL
```

## Service boundaries

| Service | Future responsibility |
|---|---|
| collector | Pull/query PostgreSQL telemetry using native observability features such as `pg_stat_statements`. |
| privacy | Strip or transform sensitive production information before any AI-boundary handoff. |
| plans | Parse and represent sanitized execution plans and plan graphs. |
| recommendations | Generate deterministic optimization candidates such as indexes, partitions, or SQL rewrites. |
| sandbox | Run controlled experiments in isolated PostgreSQL environments and integrate HypoPG where appropriate. |
| gnn | Analyze execution-plan graphs using graph neural networks. |
| rl | Search optimization strategies under bounded, measurable actions. |
| agent | Coordinate analysis and human approval workflows with LangGraph in a later phase. |

## Database separation

The normal development PostgreSQL and sandbox PostgreSQL are separate containers, volumes, credentials, and networks. The sandbox network is marked `internal` in Docker Compose. The backend is the only application service attached to that network in v0.1.

## Human control

Any future production-changing operation must be represented as an explicit, auditable proposal and require human approval before execution. No LLM is permitted to execute arbitrary production SQL.
