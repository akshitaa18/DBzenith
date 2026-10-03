# DBZenith Execution-Plan Analysis

DBZenith v0.4 adds deterministic PostgreSQL execution-plan analysis. The API obtains real plans with `EXPLAIN (FORMAT JSON)` and parses the PostgreSQL plan tree into a graph.

## API

`POST /api/v1/plans/analyze`

Provide exactly one of:

- `{"sql": "SELECT ..."}` — DBZenith runs `EXPLAIN (FORMAT JSON)` without `ANALYZE`, restricted to read-only `SELECT`, `WITH`, or `VALUES` statements.
- `{"query_id": 123}` — analyzes the latest persisted real EXPLAIN plan for a telemetry query.
- `{"plan": [...]}` — development/testing input for a previously captured PostgreSQL JSON plan.

`GET /api/v1/plans/{id}` retrieves a persisted analysis.

## Analysis pipeline

1. Raw plan enters the mandatory privacy gateway.
2. Identifiers and expressions are sanitized before persistence or visualization.
3. The sanitized plan is parsed into `PlanNode` objects and a directed plan graph.
4. Features cover sequential/index/bitmap scans, nested-loop/hash/merge joins, sorts, aggregates, parallelism, row-estimation error, loop counts, expensive operators, and filtering inefficiency.
5. A deterministic bottleneck detector emits structured findings with severity, evidence, affected node, explanation, and possible remediation.
6. The frontend renders the real graph returned by the API.

## Development verification

After the stack is running, the dashboard can analyze a real SQL statement. The same flow is available from PowerShell:

```powershell
$body = @{ sql = "SELECT * FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 20" } | ConvertTo-Json
Invoke-WebRequest http://localhost:8000/api/v1/plans/analyze -Method Post -ContentType "application/json" -Body $body | Select-Object -ExpandProperty Content
```

For multiple synthetic query shapes, see `sandbox/plan_workload.sql`. No GNN, RL, or generative model is used in v0.4.
