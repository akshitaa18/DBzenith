# DBZenith Security Policy v0.1

## Non-negotiable data boundary

Raw production data must never cross the AI boundary.

Future AI components may consume only sanitized information such as:

- normalized SQL
- structural query hashes
- tokenized identifiers
- operator types
- join topology
- sanitized execution plans
- bucketized timing
- bucketized cardinality
- workload statistics

They must not receive:

- row values or customer information
- passwords or database credentials
- API keys
- authentication tokens
- raw application payloads
- unsanitized SQL literals
- arbitrary production data

## Production safety

- Production credentials belong in environment/secret management, never source control.
- `.env` is ignored by Git; `.env.example` contains placeholders only.
- AI/LLM code must not execute arbitrary production SQL.
- Optimization experiments happen in isolated PostgreSQL sandboxes.
- Production-changing actions require explicit human approval.
- Audit logging will be required before production automation is introduced.

## v0.1 scope

Telemetry ingestion, full sanitization, RBAC, approval workflows, audit logging, HypoPG experimentation, GNN/RL execution, and production migration are not implemented yet. Their absence is intentional rather than simulated.
