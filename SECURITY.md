# DBZenith Security Policy & Hardening Architecture

## Security Invariants

DBZenith enforces three non-negotiable operational invariants across all autonomous engines and user-facing APIs:

1. **RAW DATA NEVER ENTERS THE AI BOUNDARY**: AI models (GNN cost predictors, RL policy networks, LangGraph conversational agents) receive only `AIWorkloadRecord` contracts. Literals, client parameters, passwords, API tokens, connection strings, and PII are stripped; database identifiers are masked using deterministic SHA-256 tokens (`id_...`).
2. **AI NEVER DIRECTLY MODIFIES PRODUCTION**: The advisory engines operate exclusively in read-only observation mode. Optimization experiments are executed within ephemeral, isolated sandbox containers using HypoPG virtual index constructs.
3. **PRODUCTION CHANGES REQUIRE HUMAN APPROVAL**: Every optimization proposal requires explicit sign-off in the Human-in-the-Loop Approval Center by an authenticated operator with `DBA` or `ADMIN` roles.

---

## Authentication & Role-Based Access Control (RBAC)

### Authentication Mechanism
- **Token Format**: HMAC-SHA256 authenticated URL-safe tokens with embedded user IDs, roles, issued timestamps (`iat`), and expiration timestamps (`exp`).
- **Signature Verification**: Verified in constant time via `hmac.compare_digest` to prevent timing attacks.
- **Password Storage**: PBKDF2-HMAC-SHA256 with 200,000 iterations and per-user 16-byte cryptographically random hex salts.

### Role Hierarchy
- `VIEWER` (Weight 10): Read-only access to overview telemetry, slow queries, and workload summaries.
- `ANALYST` (Weight 20): Execution plan analysis, GNN feature inspections, and safe SQL rewrite evaluations.
- `DBA` (Weight 30): Sandbox simulation execution, recommendation approval, and migration sign-off.
- `ADMIN` (Weight 40): Operator account creation, role assignment, and administrative audit inspection.

```text
[VIEWER]   --> /health, /queries, /workload
[ANALYST]  --> /plans/analyze, /rewriter/rewrite
[DBA]      --> /simulations, /recommendations/{id}/approve, /recommendations/{id}/reject
[ADMIN]    --> /auth/users, full administrative control
```

---

## Privacy Gateway Architecture

The Privacy Gateway (`backend/app/services/privacy/gateway.py`) sits between raw PostgreSQL catalogs and downstream advisory modules:

```text
Incoming SQL / Plan
         │
         ▼
[Tokenizer / Lexer]   ──> Strips line (--) and block (/* */) comments
         │
         ▼
[AST Parser]          ──> Identifies AST node boundaries and expression trees
         │
         ▼
[Literal Masker]      ──> Replaces strings with <STR>, numbers with <NUM>
         │
         ▼
[Identifier Hasher]   ──> Replaces table/column/alias names with id_<sha256>
         │
         ▼
[Structural Hasher]   ──> Computes isomorphic plan signature
         │
         ▼
[Policy Engine]       ──> Scans for leaked keys, passwords, bearer tokens, or IPs
         │
         ▼
   AIWorkloadRecord   ──> Passed to GNN / RL / Assistant
```

### Scrubbed Data Types
- Database passwords and connection URIs (`postgres://user:pass@host/db`)
- Bearer tokens and API keys (`sk_...`, `pk_...`, `api_key_...`)
- RSA/EC private keys (`-----BEGIN PRIVATE KEY-----`)
- Email addresses, telephone patterns, and UUIDs
- Raw client rows and execution plan output expressions

---

## Input Validation & Injection Defenses

1. **SQL Injection Defense**:
   - `_explain_sql` in `backend/app/api/v1/routes/plans.py` strictly permits single-statement read-only `SELECT`, `WITH`, and `VALUES` queries.
   - Semicolons (`;`), statement stacking, and SQL comments (`--`, `/*`) are rejected before optimizer planning.
2. **Sandbox Escape Defenses**:
   - `SandboxSimulator._readonly_sql` enforces strict statement isolation and blocks all data-modifying keywords (`INSERT`, `UPDATE`, `DELETE`, `ALTER`, `DROP`, `TRUNCATE`, `GRANT`, `REVOKE`, `COPY`, `EXECUTE`).
   - Sandbox databases operate on an isolated internal network without ingress access to the production database network.
3. **Prompt Injection & Tool Abuse Defenses**:
   - `AssistantSafetyPolicy` inspects incoming conversational prompts for instruction overrides (`ignore prior instructions`, `developer mode`, `dan mode`, `print system prompt`, `repeat words above`).
   - `ToolAuthorizer` gates each of the 10 assistant tools against the user's role; non-DBA roles cannot trigger `request_migration_approval`.

---

## Unified Audit Ledger

All critical actions are logged to `security_audit_events` with IP address, user agent, actor role, target entity, and structured JSON metadata:
- `AUTH`: Login successes and failed authentication attempts.
- `RECOMMENDATION`: New optimization proposals and generation runs.
- `SIMULATION`: Ephemeral HypoPG runs and benchmark measurements.
- `APPROVAL` / `REJECTION`: Operator rationale and human sign-off records.
- `MIGRATION`: Applied schema and index changes.
- `AI_BOUNDARY`: Sanitization decisions and security rejection alerts.
- `AGENT_ACTION`: Tool calls and conversational turns.

The ledger is accessible via `GET /api/v1/audit`.
