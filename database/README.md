# DBZenith PostgreSQL

The development PostgreSQL service is PostgreSQL 17 and starts with:

- `shared_preload_libraries=pg_stat_statements`
- `track_io_timing=on`

Alembic migration `0002_workload_telemetry` creates the `pg_stat_statements` extension in the `dbzenith` database and creates the telemetry persistence tables.

The optional `pg_qualstats` extension is not bundled into the official PostgreSQL image. DBZenith detects it at runtime and uses its real data when present; it never substitutes mock predicate statistics.
