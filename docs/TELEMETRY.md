# DBZenith v0.4 PostgreSQL Workload Telemetry

DBZenith v0.4 collects real PostgreSQL workload telemetry. Application endpoints do not fabricate query statistics.

## Sources

- `pg_stat_statements`: query identifier, representative normalized SQL, calls, execution timing, rows, shared/local/temp block counters, and I/O timing.
- PostgreSQL catalogs/statistics views: database/user identity plus relation-level scan, tuple, and relation-size statistics.
- `pg_qualstats`: optional. When the extension is installed, predicate occurrence/execution/filtering information is attached to matching query IDs.
- `EXPLAIN (FORMAT JSON)`: collected for eligible read-only/plannable statements in the highest-cost portion of each snapshot. Statements containing parameter placeholders are skipped because pg_stat_statements does not expose the original parameter values.

PostgreSQL requires `pg_stat_statements` to be loaded through `shared_preload_libraries` before the server starts. The development Compose service does this automatically.

## Persistence

Every collection creates a `workload_snapshots` row and the current `pg_stat_statements` rows in `query_statistics`. Relation statistics are persisted in `relation_statistics`.

Query frequency is calculated from the change in `pg_stat_statements.calls` between snapshots and expressed as calls/minute.

## APIs

- `GET /api/v1/queries/slow?page=1&page_size=20&min_mean_ms=100`
- `GET /api/v1/queries/slow?database_name=dbzenith&user_name=dbzenith`
- `GET /api/v1/queries/{query_id}`
- `GET /api/v1/workload/summary`

Slow-query detection is based on `SLOW_QUERY_THRESHOLD_MS` and compares the latest persisted observation for each query identifier.

## Synthetic workload

The development workload executes real SQL against the development PostgreSQL container.

```powershell
docker compose --profile workload run --rm workload
```

Then wait for the next telemetry collection or restart the backend. The dashboard should populate from actual PostgreSQL statistics.

## Optional pg_qualstats

The base development image intentionally does not pretend that `pg_qualstats` is installed. The collector checks for the extension at runtime and attaches predicate data only when it is genuinely available.

For a development environment where pg_qualstats is installed in the PostgreSQL image, create the extension in the target database:

```sql
CREATE EXTENSION pg_qualstats;
```

No mock predicate data is generated when it is absent.
