# DBZenith v0.7 REST API Specification

All DBZenith API endpoints are served under `/api/v1`.
Protected endpoints require HTTP Bearer token authentication in the `Authorization` header:
`Authorization: Bearer <hmac_sha256_token>`

Role-Based Access Control (RBAC) enforces minimum permissions:
- `VIEWER`: Read-only telemetry, queries, plans, health.
- `ANALYST`: Simulation, bottleneck detection, GNN scoring, AI assistant queries.
- `DBA`: Migration approvals, index execution, rollout verification.
- `ADMIN`: Full administrative control, user provisioning, security audit review.

---

## 1. Authentication & RBAC

### `POST /api/v1/auth/token`
Authenticate with credentials and obtain an HMAC-SHA256 authenticated session token.

**Request Body (`application/x-www-form-urlencoded` or JSON):**
```json
{
  "username": "dba_user",
  "password": "strong_password"
}
```

**Response (200 OK):**
```json
{
  "access_token": "dba_user.1728000000.a1b2c3d4e5f6...",
  "token_type": "bearer",
  "role": "DBA",
  "expires_in": 86400
}
```

---

## 2. Health & Readiness

### `GET /api/v1/health`
Liveness probe. Returns HTTP 200 when backend application is running.

**Response:**
```json
{
  "status": "healthy",
  "version": "0.7.0",
  "timestamp": "2026-10-04T04:00:00Z"
}
```

### `GET /api/v1/ready`
Readiness probe. Checks connectivity to production database and sandbox database.

**Response:**
```json
{
  "status": "ready",
  "database": "connected",
  "sandbox": "connected",
  "hypopg_installed": true
}
```

---

## 3. Workload & Slow Queries

### `GET /api/v1/workload/summary`
Retrieves aggregated telemetry metrics from `pg_stat_statements`.

**Response:**
```json
{
  "total_queries": 154200,
  "calls_per_second": 245.8,
  "mean_latency_ms": 14.2,
  "cache_hit_ratio": 0.984,
  "active_recommendations": 3,
  "pending_approvals": 1
}
```

### `GET /api/v1/queries/slow`
Returns paginated slow queries sorted by cumulative or mean latency.

**Query Parameters:**
- `page` (int, default: 1)
- `page_size` (int, default: 20)
- `min_mean_ms` (float, default: 5.0)
- `search` (string, optional)

**Response:**
```json
{
  "items": [
    {
      "query_fingerprint": "a3f5b7c891e204d1",
      "sanitized_query": "SELECT * FROM orders WHERE customer_id = $1 AND status = $2",
      "calls": 12500,
      "mean_exec_time_ms": 128.4,
      "total_exec_time_ms": 1605000.0,
      "rows_per_call": 14.2,
      "shared_blks_read": 48200,
      "shared_blks_hit": 182000
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

---

## 4. Execution Plans & Bottlenecks

### `POST /api/v1/plans/capture`
Retrieves and sanitizes the `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` execution plan for a query.

**Request:**
```json
{
  "sql_statement": "SELECT * FROM orders WHERE customer_id = 42"
}
```

**Privacy Guarantee:**
All literal values and runtime parameters are replaced with typed tokens (`$1`, `anon_val_...`) before plan representation is constructed.

### `GET /api/v1/plans/{fingerprint}/bottlenecks`
Analyzes structural plan bottlenecks deterministically.

**Response:**
```json
{
  "fingerprint": "a3f5b7c891e204d1",
  "bottlenecks": [
    {
      "node_type": "Seq Scan",
      "relation": "orders",
      "cost_contribution_pct": 84.5,
      "filter": "(customer_id = $1)",
      "rows_filtered": 98500,
      "recommendation": "CREATE INDEX idx_orders_customer_id ON orders(customer_id)"
    }
  ]
}
```

---

## 5. GNN Analysis & Surrogate Cost

### `POST /api/v1/gnn/infer`
Predicts relative plan latency using Graph Neural Network embedding.

**Request:**
```json
{
  "plan_graph": {
    "nodes": [...],
    "edges": [...]
  }
}
```

**Response:**
```json
{
  "predicted_relative_cost": 0.12,
  "estimated_speedup": 8.33,
  "confidence": 0.94
}
```

---

## 6. Recommendations & Simulations

### `GET /api/v1/recommendations`
Lists active index and query recommendations.

### `POST /api/v1/simulations`
Executes an isolated simulation in the sandbox using HypoPG or isolated clone.
**Never affects production.**

**Request:**
```json
{
  "recommendation_id": "rec_idx_orders_customer_id",
  "hypothetical_index_ddl": "CREATE INDEX idx_orders_customer_id ON orders(customer_id)"
}
```

**Response:**
```json
{
  "simulation_id": "sim_98234",
  "status": "VALIDATED",
  "original_cost": 4820.5,
  "hypothetical_cost": 12.4,
  "estimated_improvement_pct": 99.7,
  "write_overhead_penalty": 0.04
}
```

---

## 7. Safe SQL Rewriting

### `POST /api/v1/rewrites/generate`
Parses query AST and proposes conservative, semantically equivalent rewrites.

**Request:**
```json
{
  "query": "SELECT * FROM orders WHERE customer_id IN (SELECT id FROM customers WHERE status = 'VIP')"
}
```

**Response:**
```json
{
  "original_query": "SELECT * FROM orders WHERE customer_id IN (SELECT id FROM customers WHERE status = 'VIP')",
  "rewritten_query": "SELECT * FROM orders WHERE EXISTS (SELECT 1 FROM customers WHERE customers.id = orders.customer_id AND status = 'VIP')",
  "transformation": "IN_SUBQUERY_TO_EXISTS",
  "reason": "Eliminates materialization overhead on unbounded subquery",
  "confidence": 0.95,
  "validation_status": "PENDING_SANDBOX"
}
```

---

## 8. Human Approval Center & Controlled Migrations

### `POST /api/v1/approvals/request`
Enqueues an action for explicit DBA sign-off.

### `POST /api/v1/approvals/{id}/decide`
**Requires DBA or ADMIN role.**

**Request:**
```json
{
  "decision": "APPROVED",
  "dba_notes": "Approved for low-traffic maintenance window."
}
```

### `POST /api/v1/migrations/apply`
Applies an approved change using transaction-safe migration protocols (`CREATE INDEX CONCURRENTLY`).
**Requires DBA or ADMIN role.**

---

## 9. Conversational DBA Assistant

### `POST /api/v1/assistant/chat`
Interacts with the LangGraph-based conversational DBA assistant.
The assistant uses strictly read-only tools and privacy-sanitized execution context.

**Request:**
```json
{
  "message": "Why is the customer orders query running slow?"
}
```

**Response:**
```json
{
  "reply": "The query is performing a full sequential scan on the 'orders' table filtering by 'customer_id'...",
  "tools_invoked": ["get_slow_queries", "get_execution_plan", "analyze_plan"],
  "recommendation_id": "rec_idx_orders_customer_id"
}
```

---

## 10. Security Audit Ledger

### `GET /api/v1/audit`
**Requires ADMIN role.**
Returns immutable audit logs tracking logins, recommendations, approvals, and migrations.

**Query Parameters:**
- `action` (optional, e.g., `MIGRATION_APPLIED`, `APPROVAL_GRANTED`)
- `limit` (default: 50)
