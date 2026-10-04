# DBZenith v0.7 — Privacy-Preserving Autonomous PostgreSQL DBA

DBZenith is an enterprise-grade autonomous PostgreSQL performance optimization platform combining real telemetry, GNN surrogate cost modeling, reinforcement learning optimization policies, AST SQL rewriting, isolated HypoPG sandbox simulations, and a LangGraph conversational DBA assistant with strict human-in-the-loop approval invariants.

---

## Architecture & System Overview

```text
                               +--------------------------------------------+
                               |     DBZenith React / TypeScript Shell      |
                               |  (11 Core DBA Views: Overview, Slow Qs,    |
                               |   Plan Viewer, GNN, Recs, Simulations,     |
                               |   Approvals, Assistant, Health, Audit)     |
                               +---------------------+----------------------+
                                                     |  HTTP REST / API v1
                                                     v
                               +---------------------+----------------------+
                               |       FastAPI Enterprise Gateway           |
                               |  (Authentication, RBAC, Rate Limiting,     |
                               |   Audit Ledger, Security Headers, CORS)    |
                               +---------------------+----------------------+
                                                     |
             +-----------------------+---------------+-----------------------+
             |                       |                                       |
             v                       v                                       v
    +-----------------+    +-------------------+                   +-------------------+
    |    Telemetry    |    |  Privacy Gateway  |                   | Isolated Sandbox  |
    |    Collector    |    | (AST Sanitizer,   |                   | (HypoPG Virtual   |
    | (pg_stat_stmts, |    |  Literal Masking, |                   |  Indexes, Ephemer.|
    |  system catalog |    |  Identifier Token |                   |  Replication,     |
    |  sliding window)|    |  Structural Hash) |                   |  Regression Check)|
    +--------+--------+    +---------+---------+                   +---------+---------+
             |                       |                                       |
             +-----------+-----------+                                       |
                         |                                                   |
                         v                                                   v
           +-------------+-------------+                       +-------------+-------------+
           |     AI Boundary Guard     |                       |    Human Approval Center  |
           | (GNN Cost Model, RL Agent |                       |  (MANDATORY INVARIANT:    |
           |  DQN Policy, LangGraph)   |                       |   No Production Mutation  |
           | Raw data strictly BLOCKED |                       |   without DBA Sign-off)   |
           +---------------------------+                       +---------------------------+
```

---

## 3 Core Operational Invariants

1. **RAW DATA NEVER ENTERS THE AI BOUNDARY**: All queries and plans flow through the Privacy Gateway. Literals, client constants, passwords, API tokens, and connection strings are masked; identifiers are replaced with deterministic cryptographic hashes.
2. **AI NEVER DIRECTLY MODIFIES PRODUCTION**: The RL agent, AST rewriter, GNN engine, and LangGraph assistant operate exclusively with read permissions and sandbox simulations. Direct production mutation code paths do not exist.
3. **PRODUCTION CHANGES REQUIRE HUMAN APPROVAL**: Every candidate index, query rewrite, or partition action defaults to `requires_approval = True`. Only authenticated operators with `DBA` or `ADMIN` roles can authorize migrations.

---

## Quickstart: Running from a Clean Machine

### Option A: Complete Docker Compose Stack (Recommended - Zero Setup)

Run everything (PostgreSQL, Sandbox with HypoPG, FastAPI Backend, and Nginx Frontend) with one command:

```bash
# 1. Clone the repository
git clone https://github.com/akshitaa18/DBzenith.git
cd DBzenith

# 2. Configure Environment Variables
cp .env.example .env

# 3. Start the entire platform via Docker Compose
docker compose up -d

# 4. Open the Web Dashboard
# Visit http://localhost:8080 in your browser.
# Click "🚀 Load Demo Workload" on the Overview page to generate real e-commerce traffic,
# capture telemetry, and synthesize optimization recommendations automatically!
```

### Option B: Local Development / Manual Startup

```bash
# 1. Start PostgreSQL Databases
docker compose up -d db sandbox-db

# 2. Initialize Database Schemas & Seed Dataset
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python scripts/setup_ecommerce_db.py

# 3. Launch Backend Server (Port 8000)
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 4. Launch Frontend Dashboard (Port 8080 or Port 5173 for Vite dev)
cd ../frontend
npm install
npm run dev

# 5. Execute Complete 20-Step End-to-End Synthetic Scenario
python scripts/run_e2e_scenario.py
```

---

## Running the Automated Test Suite

```bash
# Run complete unit, security, and component tests (105 passed)
python -m pytest tests -k "not integration"

# Run PostgreSQL live integration tests
$env:DBZENITH_INTEGRATION_DATABASE_URL="postgresql+psycopg://dbzenith:change_me_dev_only@localhost:5432/dbzenith"
python -m pytest tests/integration/test_postgres_telemetry.py

# Run Frontend Production Build & TypeScript check
cd frontend
npm run build
```

---

## Security Hardening & RBAC

- **Authentication**: HMAC-SHA256 authenticated URL-safe tokens with cryptographic timestamp expiration.
- **Password Store**: PBKDF2-HMAC-SHA256 with 200,000 iterations and per-user 16-byte random hex salts.
- **Roles**:
  - `VIEWER`: Read-only access to metrics, slow queries, and summaries.
  - `ANALYST`: Query details, plan analysis, and SQL rewrite testing.
  - `DBA`: Sandbox simulation execution and human migration approval.
  - `ADMIN`: User management and full administrative authorization.
- **Unified Audit Ledger**: Immutable audit log stored in `security_audit_events` tracking logins, approvals, rejections, simulations, agent turns, and security alerts (`GET /api/v1/audit`).
- **Rate Limiting**: Sliding-window rate limiter blocking brute-force authentication (20 req/min) and API abuse (120 req/min).

---

## Demonstration Workflow

1. Navigate to `http://localhost:5173` to view the **Overview** dashboard.
2. Inspect the **Slow Queries** tab; adjust latency threshold to flag elevated queries.
3. Open **Plan Viewer** or **GNN Analysis** to inspect graph topology, bottleneck detections, and surrogate cost inferences.
4. Review **Recommendations** generated by the heuristic and RL advisory engines.
5. Launch a **Sandbox Simulation** to evaluate HypoPG virtual index performance without production impact.
6. Open **Approval Center**; verify that non-DBA roles cannot approve migrations. Enter an operator rationale and approve the migration.
7. Converse with the **DBA Assistant** powered by LangGraph using 10 strictly authorized tools.
8. Inspect **Audit Logs** to view the tamper-resistant ledger of all operator actions.

---

## Known Limitations

1. **HypoPG Sandbox Support**: HypoPG is active in the isolated sandbox PostgreSQL image; production databases must either support HypoPG or use transactional DDL emulation.
2. **PostgreSQL Version Variations**: Column names in `pg_stat_statements` differ between PG 13-16 (`blk_read_time`) and PG 17+ (`shared_blk_read_time`). DBZenith automatically handles this compatibility dynamically.
3. **Complex CTE / Window Function Rewrites**: The SQL AST rewriter conserves semantics strictly and rejects non-deterministic functions (`random()`, `uuid_generate_v4()`) or volatile queries.
4. **Production Deployment Configuration**: In a production cloud deployment (AWS RDS / GCP Cloud SQL), `shared_preload_libraries = 'pg_stat_statements'` and network firewall rules require database superuser setup.

---

## Roadmap

- [x] Real PostgreSQL telemetry collector & sliding-window snapshots
- [x] Privacy Gateway with structural AST tokenization
- [x] GNN plan graph cost surrogate model
- [x] Gymnasium RL optimization environment with DQN policy
- [x] Safe SQL AST rewriter with semantic regression verification
- [x] LangGraph conversational DBA assistant with 10 authorized tools
- [x] Complete 11-view technical DBA frontend
- [x] Enterprise security hardening (HMAC tokens, PBKDF2, RBAC, Audit Ledger)
- [ ] Multi-database cluster federation (Aurora, Citus, TimescaleDB)
- [ ] Automatic off-peak maintenance window migration scheduler
- [ ] Cross-region read-replica telemetry correlation
