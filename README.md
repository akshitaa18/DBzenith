# DBZenith v0.6

DBZenith is a privacy-preserving autonomous PostgreSQL performance optimization platform under incremental development.

## v0.6 includes

- FastAPI backend with typed configuration
- PostgreSQL + SQLAlchemy
- Alembic migration infrastructure
- Structured JSON logging
- Versioned health/readiness API
- React + TypeScript + Vite frontend shell
- Development PostgreSQL container
- Isolated sandbox PostgreSQL container
- Dockerfiles for backend and frontend
- Automated backend and frontend tests
- Real PostgreSQL workload telemetry using pg_stat_statements and PostgreSQL statistics catalogs
- Persisted workload snapshots and query statistics
- Slow-query detection with pagination and filters
- Query detail and workload summary APIs
- EXPLAIN FORMAT JSON capture for eligible statements
- Optional pg_qualstats predicate collection
- Real synthetic PostgreSQL development workload
- Privacy Gateway with sanitized execution-plan boundary
- Real execution-plan parser, graph model, feature extraction, bottleneck detection, and explanation engine
- Persisted plan analyses and plan-analysis APIs
- Frontend execution-plan visualization using real PostgreSQL plan data
- Architectural/security documentation

DBZenith v0.6 adds an isolated PostgreSQL optimization sandbox with HypoPG-backed index simulations. AI/ML optimization remains outside this release scope.

## Telemetry workflow

```text
PostgreSQL
   │
   ├── pg_stat_statements ──┐
   ├── pg_stat_user_tables ─┤
   ├── PostgreSQL catalogs ─┤──> Telemetry Collector ──> PostgreSQL persistence
   ├── optional pg_qualstats ┤
   └── EXPLAIN FORMAT JSON ─┘
                                      │
                                      ├── /queries/slow
                                      ├── /queries/{id}
                                      └── /workload/summary
```

See `docs/TELEMETRY.md` for details.

### Generate real development workload

After the stack is running:

```powershell
docker compose --profile workload run --rm workload
```

No mock query statistics are inserted by the workload or API.


## Prerequisites on Windows

Install **Git for Windows**, **Docker Desktop**, **Python 3.12+**, and **Node.js 22+**.

### PowerShell

```powershell
# 1. Clone and enter the repository
git clone <YOUR_REPOSITORY_URL> DBZenith
Set-Location DBZenith

# 2. Create local configuration
Copy-Item .env.example .env

# 3. Start the complete stack
docker compose up --build -d

# 4. Check services
docker compose ps
Invoke-WebRequest http://localhost:8000/api/v1/health | Select-Object -ExpandProperty Content
Invoke-WebRequest http://localhost:8000/api/v1/ready | Select-Object -ExpandProperty Content

# 5. Open the UI
Start-Process http://localhost:8080

# 6. Stop the stack
docker compose down
```

### Git Bash

```bash
# 1. Clone and enter the repository
git clone <YOUR_REPOSITORY_URL> DBZenith
cd DBZenith

# 2. Create local configuration
cp .env.example .env

# 3. Start the complete stack
docker compose up --build -d

# 4. Check services
docker compose ps
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready

# 5. Stop the stack
docker compose down
```

## Local backend without Docker

PowerShell:

```powershell
Set-Location backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
Set-Location ..
Copy-Item .env.example .env
Set-Location backend
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Git Bash:

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
cd ..
cp .env.example .env
cd backend
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

For local backend mode, PostgreSQL must be running and the `DATABASE_URL` in `.env` must point at it.

## Local frontend without Docker

```powershell
Set-Location frontend
npm install
npm run test
npm run build
npm run dev
```

Git Bash equivalent:

```bash
cd frontend
npm install
npm run test
npm run build
npm run dev
```

## Verification

Backend tests:

```bash
cd backend
pytest
```

Frontend tests/build:

```bash
cd frontend
npm test
npm run build
```

Docker smoke check:

```bash
docker compose up --build -d
docker compose ps
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready
curl http://localhost:8080/healthz
docker compose down
```

## Security

Read `SECURITY.md` before adding telemetry, AI, or production connectivity.

## Privacy Gateway (v0.6)

DBZenith v0.6 adds the mandatory privacy gateway: SQL AST/token parsing, literal masking, structural hashing, identifier tokenization, execution-plan sanitization, policy validation, AI-boundary contracts, and security audit logging. GNN/RL/agent execution is intentionally not implemented yet.


## v0.6 execution-plan analysis

DBZenith now analyzes real PostgreSQL `EXPLAIN (FORMAT JSON)` plans through a privacy-gated plan parser, graph model, feature extractor, deterministic bottleneck detector, and explanation engine. See `docs/PLANS.md`.

## Optimization Recommendations

DBZenith v0.6 adds deterministic Index, Partition, Query Rewrite, and Join Strategy advisors. Recommendations are persisted, require explicit approval, and never execute production DDL. Approve/reject actions are audit logged. GNN/RL are not implemented.


## v0.6 isolated optimization sandbox

See `docs/SIMULATIONS.md`. Index recommendations can be validated with `POST /api/v1/simulations` using a separate PostgreSQL 17 sandbox database. Simulation execution and benchmarks never modify production tables, and the sandbox is cleaned after each run.

## v0.7 learned plan analysis

DBZenith now includes a versioned GNN bottleneck-prediction subsystem trained only on reproducible synthetic sanitized-plan graphs. See `docs/GNN.md`. Learned inference is advisory; deterministic plan analysis remains the fallback.
