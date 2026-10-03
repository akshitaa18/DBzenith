# DBZenith Conversational DBA Assistant (LangGraph)

## Overview
DBZenith features an autonomous, security-hardened Conversational DBA Assistant powered by **LangGraph**. The assistant reasons over database workloads, analyzes EXPLAIN execution plans, formulates recommendations, and simulates changes in an isolated sandbox—strictly through controlled tools and authorization policies.

---

## Architecture & LangGraph State Machine

The assistant is structured as a compiled LangGraph `StateGraph` following a deterministic pipeline:

```
[START]
   │
   ▼
┌─────────────────────────┐
│       understand        │ ──► Prompt-injection defense & entity extraction
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│    retrieve_evidence    │ ──► Controlled tools (telemetry, plans, workload)
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│         analyze         │ ──► GNN plan analysis & bottleneck diagnosis
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│        recommend        │ ──► DBZenith recommendation engine
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│        simulate         │ ──► Sandbox simulation (HypoPG / ephemeral)
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│         explain         │ ──► Multi-faceted human-interpretable DBA report
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│    request_approval     │ ──► Formal migration request (Human Approval Gate)
└───────────┬─────────────┘
            │
            ▼
          [END]
```

---

## 10 Authorized Controlled Tools

The assistant interacts with the system exclusively through 10 gated, typed tools:

| # | Tool Name | Description | Role Required |
|---|---|---|---|
| 1 | `get_slow_queries` | Retrieves slow query statistics filtered through privacy gateway. | `viewer`, `analyst`, `dba` |
| 2 | `get_query_details` | Retrieves normalized query metrics without raw constants. | `viewer`, `analyst`, `dba` |
| 3 | `get_execution_plan` | Retrieves sanitized EXPLAIN execution plan. | `analyst`, `dba` |
| 4 | `analyze_plan` | Extracts plan features, GNN structural hashes, and bottlenecks. | `analyst`, `dba` |
| 5 | `get_recommendations` | Retrieves pending index, partition, rewrite recommendations. | `analyst`, `dba` |
| 6 | `simulate_recommendation`| Runs isolated sandbox simulation (HypoPG/ephemeral). | `dba` |
| 7 | `compare_simulations` | Compares multiple recommendation simulations side-by-side. | `dba` |
| 8 | `explain_bottleneck` | Generates natural language bottleneck diagnosis. | `analyst`, `dba` |
| 9 | `get_workload_summary` | Retrieves privacy-preserving aggregate workload stats. | `viewer`, `analyst`, `dba` |
| 10 | `request_migration_approval` | Creates human DBA review request (`pending_dba_review`). | `dba` |

---

## Strict Safety Invariants

> [!CAUTION]
> **Production Safety & Invariant Guarantees**:
> 1. **Never Execute Arbitrary SQL**: The assistant has no tool or interface to execute unconstrained SQL queries.
> 2. **Never Access Raw Production Data**: All queries route through the Privacy Gateway; queries are parameterized templates and row data is k-anonymized.
> 3. **Never Bypass Privacy Gateway**: Direct raw table dumping and credential leaks are rejected at the prompt boundary.
> 4. **Never Directly Modify Production**: Under no circumstances can the assistant mutate production relations, run DDL, or apply indexes directly.
> 5. **Never Approve Its Own Recommendation**: The agent can only *request* approval (`status="pending_dba_review"`, `requires_human_approval=True`, `agent_approved=False`). Only human DBAs can approve in the dashboard.

---

## Security Defenses

### 1. Prompt Injection Defenses
Scans every user prompt for:
- System prompt overrides (`ignore all previous instructions`, `DAN mode`, `developer mode`, `jailbreak`).
- Arbitrary SQL execution attempts (`execute raw SQL`, `DROP TABLE`, `UPDATE`, `DELETE FROM`, `UNION SELECT`).
- Data exfiltration attempts (`dump passwords`, `show credit cards`, `bypass privacy gateway`).
- Direct production mutations and self-approval (`apply directly to production`, `auto-approve recommendation`).

### 2. Tool Authorization
Role-based authorization checks (`UserRole.DBA`, `UserRole.ANALYST`, `UserRole.VIEWER`, `UserRole.UNAUTHORIZED`). Unauthorized attempts throw `SecurityViolationError`.

### 3. Audit Ledger & Conversation Logging
Every prompt evaluation, security check, tool call (with inputs and outputs), and approval staging is recorded in an immutable audit ledger (`AssistantAuditLogger`).

---

## API Endpoints

- `POST /api/v1/assistant/chat`: Sends a message to the assistant and receives a structured response containing evidence, analysis, recommendations, sandbox simulations, and approval status.
- `GET /api/v1/assistant/history/{session_id}`: Retrieves conversation turns and audit events for a session.
- `GET /api/v1/assistant/tools`: Returns metadata for all 10 controlled tools.

---

## Frontend Integration

Embedded directly in `frontend/src/pages/Dashboard.tsx` via `ConversationalDBA.tsx`:
- Interactive chat window with markdown formatting and security alert badges.
- Quick prompt buttons for common DBA operations.
- Collapsible Live Audit Ledger viewer.
- Human Approval Gate badge on staged recommendations.
