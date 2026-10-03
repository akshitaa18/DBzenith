# DBZenith v0.2 Verification Record

## Verified in the build environment

- Python AST compilation for all backend Python modules
- Backend automated tests: **5 passed, 2 skipped**
- PostgreSQL integration tests are included and automatically run when `DBZENITH_INTEGRATION_DATABASE_URL` points to a live PostgreSQL instance.
- Docker Compose YAML parsing
- Frontend `package.json` JSON validation
- Final artifact cleanup audit
- No `.env`, virtual environment, `node_modules`, caches, build outputs, or `.git` directory included

## Runtime verification requiring Docker/PostgreSQL

The execution environment used to prepare this artifact did not expose the Docker CLI, so a live Docker Compose PostgreSQL runtime could not be executed here.

The v0.2 runtime is configured for PostgreSQL 17 with `pg_stat_statements`, `compute_query_id=on`, `pg_stat_statements.track=all`, and `track_io_timing=on`. The backend migration creates the extension after the server starts.

Run the full runtime verification on the development machine:

```powershell
docker compose down -v
docker compose up --build -d
docker compose ps
Invoke-WebRequest http://localhost:8000/api/v1/health | Select-Object -ExpandProperty Content
Invoke-WebRequest http://localhost:8000/api/v1/ready | Select-Object -ExpandProperty Content
Invoke-WebRequest http://localhost:8000/api/v1/workload/summary | Select-Object -ExpandProperty Content
docker compose --profile workload run --rm workload
Invoke-WebRequest "http://localhost:8000/api/v1/queries/slow?page=1&page_size=20&min_mean_ms=1" | Select-Object -ExpandProperty Content
```

Then refresh `http://localhost:8080`.
