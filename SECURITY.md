# DBZenith Security Policy v0.6

## Mandatory privacy boundary

DBZenith treats the privacy gateway as a mandatory security boundary between raw PostgreSQL telemetry and any future AI/ML component.

Raw production information may be observed by the collector, but **AI-facing code may consume only `AIWorkloadRecord`**, whose query and plan fields are sanitized contracts.

### Explicit contracts

- `RawQuery` — ingestion-only SQL containing the original query text.
- `SanitizedQuery` — normalized, literal-free, structurally hashed SQL with schema/table/column identifiers replaced by deterministic tokens.
- `RawPlan` — ingestion-only PostgreSQL `EXPLAIN (FORMAT JSON)` output.
- `SanitizedPlan` — execution-plan structure with relation identifiers tokenized and expression-bearing fields sanitized.
- `AIWorkloadRecord` — the only workload contract accepted by AI-facing code.

`RawQuery` and `RawPlan` must never be passed directly to AI modules.

## Sanitization guarantees

The privacy gateway:

1. Removes SQL line and block comments.
2. Parses SQL into a structural AST of tokens and nested groups.
3. Masks string literals, numbers, parameters, dollar-quoted values, and sensitive token classes.
4. Detects and removes common email addresses, phone numbers, UUIDs, IPv4 addresses, API-key-like values, and password values.
5. Tokenizes schema, table, column, alias, and other SQL identifiers using deterministic SHA-256-derived identifiers.
6. Produces a structural hash from the sanitized representation, so changing literal values does not change the structural hash.
7. Sanitizes execution-plan relation names and expression-bearing fields and fail-closes unknown plan text.
8. Runs a policy check before an AI record can be constructed.
9. Emits structured security audit events without logging raw SQL, raw plans, or payloads. Audit decisions are persisted in `privacy_audit_events` when the DB is available.

## AI boundary enforcement

`AIBoundaryValidator` accepts `AIWorkloadRecord` only. Passing `RawQuery`, `RawPlan`, dictionaries containing raw fields, or other types is rejected.

This is a runtime contract boundary; static type checking can complement it but is not treated as the security control by itself.

## Sensitive data that must not reach AI

- row values or customer information
- passwords and database credentials
- API keys and authentication tokens
- email addresses and phone numbers
- UUIDs and IP addresses when they occur as values
- JSON/application payload values
- SQL comments containing sensitive content
- unsanitized SQL literals
- raw execution-plan expressions containing values

## Production safety

- Production credentials belong in environment/secret management, never source control.
- `.env` is ignored by Git; `.env.example` contains placeholders only.
- AI/LLM code must not execute arbitrary production SQL.
- Optimization experiments happen in isolated PostgreSQL sandboxes.
- Production-changing actions require explicit human approval.
- GNN/RL/agent components are not implemented in v0.6.

## Fail-closed behavior

If SQL parsing, plan sanitization, policy validation, or an AI-boundary check fails, DBZenith rejects the handoff rather than forwarding partially sanitized data.


## Execution-plan security boundary (v0.6)

Execution plans can contain relation names, index names, predicates, output expressions, and other workload details. Every plan submitted to the analysis API crosses the existing Privacy Gateway before analysis results are persisted. Identifier-bearing fields are tokenized and expression fields are literal-masked. Unknown textual plan fields are dropped rather than forwarded.

The SQL analysis path accepts only a single read-only `SELECT`, `WITH`, or `VALUES` statement and uses `EXPLAIN (FORMAT JSON)` without `ANALYZE`, so the submitted SQL is planned but not executed. A 5-second local statement timeout limits planning work.

## Optimization Recommendations

DBZenith v0.6 adds deterministic Index, Partition, Query Rewrite, and Join Strategy advisors. Recommendations are persisted, require explicit approval, and never execute production DDL. Approve/reject actions are audit logged. GNN/RL are not implemented.


## v0.6 simulation boundary

Optimization simulations execute only against the isolated sandbox PostgreSQL instance. HypoPG is installed in the sandbox only. Production tables are never modified by simulations. Sandbox DDL, benchmark indexes, and HypoPG state are cleaned after each run; timeouts, temp-file limits, row-copy caps, and benchmark limits constrain resource use.

### Learned-model boundary

The GNN consumes only sanitized plan graphs and numeric features. Training data is synthetic and reproducible. Model artifacts contain weights/normalization statistics only; production row values and raw SQL literals are not included.
