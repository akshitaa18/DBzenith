DBZenith
Privacy-Preserving Autonomous PostgreSQL Database Optimization
DBZenith is an AI-assisted PostgreSQL performance optimization platform that analyzes database workloads, identifies query bottlenecks, recommends optimizations, and evaluates potential changes in an isolated sandbox. It combines workload telemetry, privacy-preserving SQL abstraction, Graph Neural Network (GNN) analysis, Reinforcement Learning (RL), SQL rewriting, HypoPG simulations, and a LangGraph-powered DBA assistant.
Core principle: AI recommends, the sandbox validates, and authorized humans approve production changes.
Table of Contents
Features
Architecture
Technology Stack
Getting Started
Accessing the Application
How It Works
Security Design
Testing
Project Structure
Environment Configuration
Important Notes

Features
PostgreSQL workload monitoring — collect query and relation statistics using PostgreSQL telemetry, including `pg_stat_statements`.
Slow-query analysis — inspect query performance and execution plans to identify possible bottlenecks.
Privacy Gateway — mask SQL literals, tokenize identifiers, sanitize execution-plan data, and generate structural metadata before AI analysis.
GNN execution-plan analysis — represent execution plans as graphs to help identify expensive operators and potential optimization opportunities.
Reinforcement Learning — evaluate candidate optimization actions using a reward model that considers performance benefits and operational costs.
SQL AST rewriting — generate candidate query rewrites and validate them before presenting recommendations.
Isolated PostgreSQL sandbox — use a separate PostgreSQL environment with HypoPG to evaluate hypothetical indexes without creating them on the production database.
LangGraph DBA assistant — interact with the optimization workflow through a conversational assistant with controlled tools.
Human-in-the-loop approvals — require authorized operator approval before production-impacting changes.
Role-based access control (RBAC) — separate permissions for viewers, analysts, DBAs, and administrators.
Audit logging — record important security, analysis, simulation, and approval events.
Interactive dashboard — review workload health, slow queries, execution plans, recommendations, simulations, approvals, and audit information.
Docker Compose deployment — run the application and its supporting services in a reproducible local environment.
Architecture
```text
                         React + TypeScript Dashboard
                                      |
                                      v
                              FastAPI Backend
                         Authentication / RBAC / API
                                      |
                  +-------------------+-------------------+
                  |                   |                   |
                  v                   v                   v
          PostgreSQL Telemetry   Privacy Gateway    Sandbox PostgreSQL
          Query/Relation Stats   Mask + Abstract     + HypoPG
                  |                   |                   |
                  |                   v                   |
                  |             Sanitized Data             |
                  |                   |                   |
                  |          +--------+--------+           |
                  |          |        |        |           |
                  |          v        v        v           |
                  |         GNN       RL    LangGraph       |
                  |          |        |        |           |
                  +----------+--------+--------+-----------+
                                      |
                                      v
                           Recommendations / Simulation
                                      |
                                      v
                              Human Approval
                                      |
                                      v
                           Auditing and Traceability
```
Technology Stack
Layer	Technologies
Frontend	React, TypeScript, Vite
Backend API	Python, FastAPI, SQLAlchemy, Pydantic
Database	PostgreSQL 17, `pg_stat_statements`
Sandbox	PostgreSQL, HypoPG
AI and optimization	PyTorch, PyTorch Geometric, Gymnasium, DQN, LangGraph
Database migrations	Alembic
Deployment	Docker, Docker Compose, Nginx
Frontend testing	Vitest
Backend testing	Pytest
Getting Started
Prerequisites
For the Docker-based setup, install:
Git
Docker Desktop or Docker Engine with the Docker Compose plugin
For manual development, you will also need Python 3.12 and Node.js/npm.
1. Clone the repository
```bash
git clone https://github.com/akshitaa18/DBzenith.git
cd DBzenith
```
2. Configure environment variables
Create a local environment file from the example:
macOS/Linux/Git Bash
```bash
cp .env.example .env
```
Windows PowerShell
```powershell
Copy-Item .env.example .env
```
The example values are intended for local development. Change them before exposing the application or using any non-development environment.
3. Build and start the application
```bash
docker compose up -d --build
```
Docker Compose starts the application services, PostgreSQL databases, sandbox, and workload initialization service.
To check service status:
```bash
docker compose ps
```
To inspect logs:
```bash
docker compose logs -f
```
4. Load and explore the demo workload
Open the dashboard and use Load Demo Workload on the Overview page if the control is available. This generates sample workload activity for the platform to analyze.
To stop the application:
```bash
docker compose down
```
To stop the application and remove persisted database volumes (this deletes local database data):
```bash
docker compose down -v
```
Accessing the Application
Once the services are running:
Service	URL
Web dashboard	http://localhost:8080
Backend API	http://localhost:8000
Interactive API documentation	http://localhost:8000/docs
Main PostgreSQL	`localhost:5432`
Sandbox PostgreSQL	`localhost:5433`
The backend health endpoint is available at `http://localhost:8000/api/v1/health`.
How It Works
Collect: gather query workload and database performance statistics.
Protect: sanitize SQL and execution-plan information before AI processing.
Analyze: inspect execution-plan structure and identify potential bottlenecks.
Recommend: generate candidate indexes, query rewrites, or other optimization strategies.
Simulate: evaluate candidate changes in the isolated sandbox where supported.
Review: present estimated benefits, costs, and risks in the dashboard.
Approve: require an authorized human to approve production-impacting changes.
Audit: record relevant actions for traceability.
Security Design
DBZenith is designed around three operational safeguards:
Privacy boundary: sensitive literals and other protected information should be sanitized before data is sent to AI components.
Production protection: AI analysis and optimization experiments are separated from direct production database modification.
Human approval: production-impacting changes require approval from an authorized DBA or administrator.
Additional controls include authentication, role-based authorization, restricted assistant tools, security middleware, and audit logging.
> **Important:** These controls should be reviewed and tested before connecting DBZenith to any real production database. Do not treat a development configuration as production-hardened.
Testing
Backend tests
Run from the repository root:
```bash
python -m pytest tests -k "not integration"
```
Frontend tests
```bash
cd frontend
npm install
npm run test
```
Frontend production build
```bash
npm run build
```
Integration tests may require the PostgreSQL services and environment variables to be configured first. Consult the test files and project documentation for the exact requirements.
Project Structure
```text
DBzenith/
├── ai/                 # AI models and optimization components
├── backend/            # FastAPI application and services
│   ├── app/
│   │   ├── api/        # API routes
│   │   ├── core/       # Configuration and core utilities
│   │   ├── db/         # Database integration
│   │   ├── models/     # Data models
│   │   └── services/   # Privacy, telemetry, GNN, RL, sandbox, etc.
│   └── alembic/        # Database migrations
├── database/           # Database-related assets
├── docs/               # Project documentation
├── frontend/           # React + TypeScript dashboard
├── sandbox/            # Sandbox database and workload assets
├── scripts/            # Setup and utility scripts
├── tests/              # Automated tests
├── docker-compose.yml  # Multi-service local environment
├── .env.example        # Example environment configuration
├── ARCHITECTURE.md     # Architecture documentation, if present
└── SECURITY.md         # Security documentation, if present
```
Environment Configuration
The `.env.example` file documents the main configuration values, including:
Application environment and logging
Backend port and CORS origins
PostgreSQL database name, user, password, and port
Sandbox database configuration
Telemetry thresholds and collection limits
Simulation safety limits
Frontend API base URL
Do not commit a real `.env` file, passwords, API keys, or other secrets to version control.
Important Notes
DBZenith is intended for development, demonstration, and controlled evaluation unless it has been independently hardened for production.
HypoPG evaluates hypothetical indexes; it does not guarantee that a proposed change will improve every real workload.
Estimated query plans and sandbox benchmarks may differ from production behavior due to data size, statistics, hardware, concurrency, and configuration.
Always validate recommendations in a staging environment and take appropriate backups before making database changes.
Replace example credentials, restrict network access, and review database permissions before any deployment beyond a local development environment.

If you find this project useful, consider giving the repository a ⭐ on GitHub.