# DBZenith v0.6 — Isolated Optimization Simulations

DBZenith v0.6 adds an isolated PostgreSQL optimization sandbox. It validates index recommendations without changing production tables.

## Isolation boundary

- `db` is the production/telemetry PostgreSQL container.
- `sandbox-db` is a separate PostgreSQL 17 container, volume, user, and internal-only Docker network.
- HypoPG is installed only in `sandbox-db`.
- The sandbox never receives the production database credentials.
- Simulation DDL, HypoPG metadata, and benchmark indexes exist only in the sandbox and are removed after the simulation.

The backend can read production telemetry/catalog metadata through its normal read path so it can replicate the minimum required schema/data. Simulation execution and benchmark execution use only `SANDBOX_DATABASE_URL`.

## Simulation flow

For an index recommendation:

1. resolve the recommendation and affected telemetry queries
2. replicate affected production table schemas and a bounded sample of rows into the sandbox
3. recreate existing non-constraint indexes and run `ANALYZE`
4. run baseline `EXPLAIN (FORMAT JSON)`
5. create a HypoPG hypothetical index
6. run proposed `EXPLAIN (FORMAT JSON)`
7. compare planner costs and access-node changes
8. estimate storage and write-maintenance impact from production catalog statistics
9. optionally benchmark the query before and after a real index created only inside the sandbox
10. drop the sandbox index, reset HypoPG, and drop the sandbox schema

## API

`POST /api/v1/simulations`

Example request:

```json
{
  "recommendation_id": 12,
  "benchmark_runs": 3,
  "statement_timeout_ms": 5000,
  "max_rows_per_table": 25000
}
```

`GET /api/v1/simulations/{id}` returns:

- baseline cost
- proposed cost
- estimated improvement
- affected queries
- plan differences
- estimated storage impact
- write overhead estimate
- confidence
- benchmark measurements
- limitations

## Resource and safety limits

- only `SELECT`, `WITH`, and `VALUES` workload statements may be simulated
- per-statement timeout is bounded to 30 seconds
- lock timeout is capped at 2 seconds
- temp files are capped at 128 MB
- parallel query workers are disabled for deterministic local comparisons
- copied table rows are bounded per simulation
- benchmark runs are bounded to five per affected query
- a process-wide simulation lock serializes sandbox resets
- cleanup runs in a `finally` block even after simulation failure

## Limitations

HypoPG provides planner-level hypothetical index validation; it does not provide an exact physical index size. Storage is therefore reported as an estimate/unavailable until a real sandbox-only index is created. Write overhead is classified from observed table write activity because exact per-index CPU overhead cannot be measured before index creation. Normalized `pg_stat_statements` parameters are replaced with representative typed values, so the comparison is an estimate for the observed query shape rather than a production benchmark.
