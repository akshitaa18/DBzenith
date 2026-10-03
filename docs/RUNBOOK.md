# DBZenith v0.2 Runbook

## Clean start

```powershell
Copy-Item .env.example .env
docker compose down -v
docker compose up --build -d
docker compose ps
```

Verify:

```powershell
Invoke-WebRequest http://localhost:8000/api/v1/health | Select-Object -ExpandProperty Content
Invoke-WebRequest http://localhost:8000/api/v1/ready | Select-Object -ExpandProperty Content
Invoke-WebRequest http://localhost:8000/api/v1/workload/summary | Select-Object -ExpandProperty Content
```

Open `http://localhost:8080`.

## Generate real telemetry

```powershell
docker compose --profile workload run --rm workload
```

The workload runs actual SQL against `dbzenith`. Wait up to the configured telemetry interval, then refresh the dashboard.

## Useful API calls

```powershell
Invoke-WebRequest "http://localhost:8000/api/v1/queries/slow?page=1&page_size=20&min_mean_ms=1" | Select-Object -ExpandProperty Content
Invoke-WebRequest "http://localhost:8000/api/v1/workload/summary" | Select-Object -ExpandProperty Content
```

## Migrations

The backend container runs:

```text
alembic upgrade head
```

before Uvicorn starts.

## Fresh database

If changing PostgreSQL startup parameters or extension configuration during development:

```powershell
docker compose down -v
docker compose up --build -d
```

This removes only the local development database volumes and recreates them.

## Shutdown

```powershell
docker compose down
```
