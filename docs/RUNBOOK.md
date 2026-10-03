# DBZenith Operations & Developer Runbook (v0.7)

This runbook provides complete operational procedures for clean-machine setup, local development, full end-to-end demo execution, testing, and production deployment.

---

## 1. Clean-Machine Quick Start

### Prerequisites
- **OS**: Linux, macOS, or Windows (WSL2 recommended for Docker)
- **Docker & Docker Compose**: v24.0+ (Compose v2.20+)
- **Python**: 3.11+ (if running tests locally)
- **Node.js & npm**: Node 18+ (if building the frontend locally)

### Steps to Run
```bash
# 1. Clone repository
git clone https://github.com/akshitaa18/DBzenith.git
cd DBzenith

# 2. Configure environment
cp .env.example .env

# 3. Spin up full container stack (Backend, Frontend, Sandbox DB, Workload DB)
docker compose down -v
docker compose up --build -d

# 4. Verify system health
curl -s http://localhost:8000/api/v1/health | jq .
curl -s http://localhost:8000/api/v1/ready | jq .

# 5. Open DBA Dashboard
# Navigate to http://localhost:8080 in your browser
```

---

## 2. Step-by-Step Demo Guide (20-Step E2E Scenario)

DBZenith includes a self-contained, 20-step synthetic PostgreSQL scenario script demonstrating the complete optimization loop:

```bash
# Run against the live Docker PostgreSQL database
python scripts/run_e2e_scenario.py
```

### What the Scenario Demonstrates:
1. **Schema Creation**: Creates `customers`, `orders`, and `order_items` tables with constraints.
2. **Synthetic Data**: Injects 1,000 customers, 10,000 orders, and 25,000 line items.
3. **Workload Generation**: Generates concurrent parameterized queries.
4. **Telemetry Ingestion**: Gathers query execution metrics from `pg_stat_statements`.
5. **Slow Query Discovery**: Detects an unindexed query taking sequential scan overhead.
6. **Plan Capture & Sanitization**: Captures `EXPLAIN (ANALYZE, BUFFERS)` and passes it through the Privacy Gateway to scrub literal values.
7. **Graph Construction**: Constructs directed acyclic execution plan graph.
8. **Deterministic Bottleneck Detection**: Pinpoints sequential scan with high row rejection.
9. **GNN Cost Scoring**: Computes learned structural embeddings and predicts relative speedup.
10. **Recommendation Engine**: Generates index recommendation (`CREATE INDEX CONCURRENTLY idx_orders_customer_id ON orders(customer_id)`).
11. **RL Policy Evaluation**: RL agent scores state and validates action against baseline policy.
12. **Safe SQL Rewriter**: Demonstrates AST-based conservative SQL transformations.
13. **HypoPG Sandbox Validation**: Deploys hypothetical index in isolated sandbox to evaluate cost reduction without table locking.
14. **Impact Measurement**: Computes measured cost reduction (e.g., 98%+ cost drop).
15. **Approval Center Enqueue**: Recommendation is submitted to DBA Approval Center.
16. **Role Authorization Check**: Confirms non-DBA roles cannot approve migrations.
17. **Explicit DBA Approval**: DBA evaluates impact metrics and explicitly approves change.
18. **Transaction-Safe Migration**: Applies migration using concurrent zero-downtime execution.
19. **Index Verification**: Verifies index registration in `pg_indexes` catalog.
20. **Post-Change Telemetry Verification**: Re-runs query and verifies index scan acceleration.

---

## 3. Developer Guide & Test Suite

### Running the Full Test Suite
```bash
# Set Python path
export PYTHONPATH=backend  # or set PYTHONPATH=backend in Windows PowerShell

# Run all unit, security, and component tests
pytest tests -k "not integration" -v

# Run live PostgreSQL integration tests (requires live PG running)
pytest tests/integration/test_postgres_telemetry.py -v

# Run Frontend build check
cd frontend
npm install
npm run build
```

### Running the Conversational DBA Assistant
The assistant uses LangGraph with strictly controlled read-only tools:
```python
from backend.app.services.assistant.graph import build_assistant_graph

graph = build_assistant_graph()
response = graph.invoke({
    "messages": [{"role": "user", "content": "What queries are causing high latency?"}],
    "user_role": "ANALYST"
})
print(response["messages"][-1].content)
```

---

## 4. Production Deployment Guide

### Deployment Architecture
- **Production DB**: Monitored via read-only telemetry user with access to `pg_stat_statements`.
- **Sandbox DB**: Dedicated container or ephemeral clone equipped with `hypopg` extension.
- **Backend API**: Stateless FastAPI containers behind an HTTPS reverse proxy (e.g., Traefik / Nginx / ALB).
- **Frontend**: Static SPA hosted via Nginx, Cloudflare Pages, or AWS S3+CloudFront.

### Key Deployment Considerations
1. **Never share credentials between Sandbox and Production**: Sandbox must have no network access to production tables.
2. **PostgreSQL Configuration**: Ensure `shared_preload_libraries = 'pg_stat_statements'` is set in `postgresql.conf` on the production instance.
3. **Secret Rotation**: Set `SECRET_KEY` via a hardware security module (HSM) or secret manager (AWS Secrets Manager, HashiCorp Vault). Never use the dev default.
4. **Audit Log Persistence**: Ensure the `security_audit_events` table or application logs are forwarded to a SIEM (e.g., Datadog, Splunk, Elastic) for tamper-evident compliance archiving.
