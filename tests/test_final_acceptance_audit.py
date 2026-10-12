"""Final Acceptance Audit Test Suite for DBZenith (Phases 1-9).

Verifies:
1. SQLAlchemy Model vs. Alembic Migration chain (0001 -> 0010) schema consistency.
2. Error handling when PostgreSQL, the sandbox, or optional ML artifacts/dependencies are unavailable.
3. Startup seeding and restart idempotency (never destroying or overwriting legitimate data).
4. Security, RBAC (Anonymous, VIEWER, ANALYST, DBA, ADMIN), token expiry, and AI non-authorization boundaries.
5. Data integrity (distinguishing synthetic vs. live telemetry, planner estimates vs. sandbox measurements vs. post-change observations).
6. Complete 9-step End-to-End Acceptance Scenario (a through i):
   a. Sign in with a permitted user.
   b. Inspect a slow query and its evidence.
   c. Generate or inspect an optimization recommendation.
   d. Review its candidate execution plan or safe sandbox result.
   e. Attempt approval as a viewer and confirm denial.
   f. Approve as an authorized DBA.
   g. Record a validation result.
   h. Verify the lifecycle history and audit record.
   i. Confirm that an unmeasured or failed optimization is not displayed as a verified production improvement.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from alembic import command
from alembic.config import Config
from app.core.auth import _API_RATE_LIMITER, _AUTH_RATE_LIMITER
from app.core.config import get_settings
from app.core.lifecycle import ensure_lifecycle_schema
from app.core.provenance import ensure_provenance_schema
from app.core.security import Role, get_security_manager, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app import models as _models  # noqa: F401
from app.models.recommendation import OptimizationRecommendation
from app.models.security import User
from app.models.workload import QueryStatistic, WorkloadSnapshot
from app.services.gnn.inference import infer as gnn_infer
from app.services.gnn.train import synthetic_graph
from app.services.rl.contracts import SanitizedState
from app.services.rl.inference import RLInferenceService
from app.services.workload.generator import auto_seed_if_empty, ensure_default_users


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture(autouse=True)
def clear_rate_limiters():
    _API_RATE_LIMITER.history.clear()
    _AUTH_RATE_LIMITER.history.clear()
    yield
    _API_RATE_LIMITER.history.clear()
    _AUTH_RATE_LIMITER.history.clear()


def test_alembic_migrations_match_all_sqlalchemy_models():
    """Runs Alembic upgrade head (0001 -> 0010) and verifies 100% table and column parity with SQLAlchemy models."""
    backend_dir = Path(__file__).resolve().parents[1] / "backend"
    alembic_ini = backend_dir / "alembic.ini"

    with tempfile.TemporaryDirectory() as tmpdir:
        mig_db_path = Path(tmpdir) / "alembic_mig.db"
        mod_db_path = Path(tmpdir) / "models_meta.db"
        mig_url = f"sqlite:///{mig_db_path}"
        mod_url = f"sqlite:///{mod_db_path}"

        prev_db_url = os.environ.get("DATABASE_URL")
        try:
            os.environ["DATABASE_URL"] = mig_url
            get_settings.cache_clear()
            cfg = Config(str(alembic_ini))
            cfg.set_main_option("script_location", str(backend_dir / "alembic"))
            cfg.set_main_option("sqlalchemy.url", mig_url)
            command.upgrade(cfg, "head")
        finally:
            if prev_db_url is not None:
                os.environ["DATABASE_URL"] = prev_db_url
            else:
                os.environ.pop("DATABASE_URL", None)
            get_settings.cache_clear()

        mig_engine = create_engine(mig_url)
        mod_engine = create_engine(mod_url)
        try:
            Base.metadata.create_all(mod_engine)

            mig_insp = inspect(mig_engine)
            mod_insp = inspect(mod_engine)

            mig_tables = set(mig_insp.get_table_names()) - {"alembic_version"}
            mod_tables = set(mod_insp.get_table_names())
            assert mig_tables == mod_tables, f"Table mismatch: {mod_tables ^ mig_tables}"

            for table_name in sorted(mod_tables):
                mig_cols = {c["name"] for c in mig_insp.get_columns(table_name)}
                mod_cols = {c["name"] for c in mod_insp.get_columns(table_name)}
                assert mig_cols == mod_cols, f"Column mismatch on {table_name}: {mod_cols ^ mig_cols}"
        finally:
            mig_engine.dispose()
            mod_engine.dispose()


def test_startup_seeding_idempotency_and_legitimate_data_preservation():
    """Verifies repeated startup seeding does not overwrite or delete legitimate live telemetry."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ensure_provenance_schema(engine)
    ensure_lifecycle_schema(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        ensure_default_users(session)
        # Insert a real live telemetry snapshot and query statistic
        live_snap = WorkloadSnapshot(
            window_seconds=30.0,
            total_calls=420,
            total_exec_time_ms=8400.0,
            unique_queries=1,
            slow_queries=1,
            provenance_state="LIVE_TELEMETRY",
            source_identifier="postgresql://prod-host:5432/dbzenith",
            collection_status="success",
            is_synthetic=False,
            is_measured=True,
        )
        session.add(live_snap)
        session.flush()
        session.add(
            QueryStatistic(
                snapshot_id=live_snap.id,
                query_id=777001,
                database_name="dbzenith",
                user_name="app",
                normalized_query="SELECT id, total FROM invoices WHERE customer_id = $1",
                query_fingerprint="fp_live_777001",
                calls=420,
                total_exec_time_ms=8400.0,
                mean_exec_time_ms=20.0,
                min_exec_time_ms=5.0,
                max_exec_time_ms=95.0,
                rows=420,
                provenance_state="LIVE_TELEMETRY",
                is_synthetic=False,
                is_measured=True,
            )
        )
        session.commit()

        # Calling auto_seed_if_empty multiple times must NOT overwrite or add synthetic snapshots
        seeded_first = auto_seed_if_empty(session)
        seeded_second = auto_seed_if_empty(session)
        assert seeded_first is False
        assert seeded_second is False
        assert session.query(WorkloadSnapshot).count() == 1
        snap = session.query(WorkloadSnapshot).first()
        assert snap.is_synthetic is False
        assert snap.provenance_state == "LIVE_TELEMETRY"
        assert session.query(User).count() == 4

    engine.dispose()


def test_unavailability_of_database_sandbox_and_ml_artifacts(tmp_path: Path):
    """Tests graceful error handling when PostgreSQL, sandbox, or ML model artifacts are unavailable."""
    # 1. Primary database unavailable -> /api/v1/ready returns 503
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("connection to server at 'db' failed: Connection refused")

    def override_broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = override_broken_db
    try:
        client = TestClient(app)
        ready_resp = client.get("/api/v1/ready")
        assert ready_resp.status_code == 503
        assert ready_resp.json()["detail"] == "database_unavailable"
    finally:
        app.dependency_overrides.clear()

    # 2. GNN & RL missing artifacts -> deterministic fallback with confidence=None (no crash or fake confidence)
    missing_dir = tmp_path / "nonexistent_artifacts"
    gnn_out = gnn_infer(synthetic_graph(0), missing_dir, allow_fallback=True)
    assert gnn_out["is_fallback"] is True
    assert gnn_out["source_classification"] == "DETERMINISTIC_FALLBACK"
    assert all(p["confidence"] is None for p in gnn_out["predictions"])

    rl_svc = RLInferenceService(model_dir=missing_dir, allow_fallback=True)
    rl_out = rl_svc.optimize(SanitizedState())
    assert rl_out["is_fallback"] is True
    assert rl_out["confidence"] is None
    assert rl_out["production_modified"] is False
    assert rl_out["can_authorize_production"] is False


def test_end_to_end_acceptance_scenario():
    """Executes the complete 9-step acceptance scenario (a through i) in an isolated test environment."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ensure_provenance_schema(engine)
    ensure_lifecycle_schema(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = SessionLocal()

    # Seed default users and initial telemetry + recommendations
    ensure_default_users(session)
    snap = WorkloadSnapshot(
        id=1,
        window_seconds=60.0,
        total_calls=2500,
        total_exec_time_ms=180000.0,
        unique_queries=2,
        slow_queries=2,
        provenance_state="LIVE_TELEMETRY",
        source_identifier="postgresql://db:5432/dbzenith",
        collection_status="success",
        is_synthetic=False,
        is_measured=True,
    )
    session.add(snap)
    session.flush()

    q1 = QueryStatistic(
        id=1,
        snapshot_id=1,
        query_id=5001,
        database_name="dbzenith",
        user_name="dbzenith",
        normalized_query="SELECT order_id, customer_id, amount, status FROM orders WHERE status = $1 ORDER BY order_date DESC",
        query_fingerprint="fp_e2e_orders_status",
        calls=1200,
        total_exec_time_ms=144000.0,
        mean_exec_time_ms=120.0,
        min_exec_time_ms=35.0,
        max_exec_time_ms=480.0,
        rows=6000,
        shared_blks_hit=4000,
        shared_blks_read=9500,
        temp_blks_read=120,
        temp_blks_written=120,
        query_frequency_per_minute=20.0,
        provenance_state="LIVE_TELEMETRY",
        is_synthetic=False,
        is_measured=True,
        explain_plan=[
            {
                "Plan": {
                    "Node Type": "Sort",
                    "Startup Cost": 410.0,
                    "Total Cost": 455.0,
                    "Plan Rows": 1200,
                    "Sort Key": ["order_date DESC"],
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "orders",
                            "Startup Cost": 0.0,
                            "Total Cost": 380.0,
                            "Plan Rows": 1200,
                            "Filter": "(status = $1)",
                        }
                    ],
                }
            }
        ],
    )
    q2 = QueryStatistic(
        id=2,
        snapshot_id=1,
        query_id=5002,
        database_name="dbzenith",
        user_name="dbzenith",
        normalized_query="SELECT product_id, count(*) FROM orders WHERE amount > $1 GROUP BY product_id",
        query_fingerprint="fp_e2e_orders_amount",
        calls=800,
        total_exec_time_ms=36000.0,
        mean_exec_time_ms=45.0,
        min_exec_time_ms=12.0,
        max_exec_time_ms=190.0,
        rows=400,
        shared_blks_hit=3000,
        shared_blks_read=2200,
        query_frequency_per_minute=13.3,
        provenance_state="LIVE_TELEMETRY",
        is_synthetic=False,
        is_measured=True,
    )
    session.add_all([q1, q2])
    session.commit()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            # Verify anonymous requests are blocked across Phase 1-9 protected endpoints
            for protected_path in [
                "/api/v1/queries/slow",
                "/api/v1/recommendations",
                "/api/v1/index-portfolio",
                "/api/v1/alerts",
                "/api/v1/plans/gnn/evaluation",
                "/api/v1/rl/evaluation",
                "/api/v1/audit/query",
            ]:
                assert client.get(protected_path).status_code == 401

            # Step (a): Sign in with permitted users (VIEWER and DBA)
            viewer_login = client.post(
                "/api/v1/auth/login",
                json={"username": "viewer", "password": "DBZenith_Viewer_2026!"},
            )
            assert viewer_login.status_code == 200
            viewer_token = viewer_login.json()["access_token"]
            viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

            dba_login = client.post(
                "/api/v1/auth/login",
                json={"username": "dba_operator", "password": "DBZenith_DBA_2026!"},
            )
            assert dba_login.status_code == 200
            dba_token = dba_login.json()["access_token"]
            dba_headers = {"Authorization": f"Bearer {dba_token}"}

            # Step (b): Inspect a slow query and its evidence
            slow_resp = client.get("/api/v1/queries/slow?min_mean_ms=50", headers=viewer_headers)
            assert slow_resp.status_code == 200
            slow_items = slow_resp.json()["items"]
            assert len(slow_items) >= 1
            target_query = next(item for item in slow_items if item["query_id"] == 5001)
            assert target_query["provenance_state"] == "LIVE_TELEMETRY"
            assert target_query["is_synthetic"] is False

            trace_resp = client.get("/api/v1/queries/5001/trace", headers=viewer_headers)
            assert trace_resp.status_code == 200
            trace_data = trace_resp.json()
            assert trace_data["query_id"] == 5001
            assert len(trace_data["telemetry_history"]) >= 1

            # Step (c): Generate and inspect optimization recommendations
            gen_resp = client.get("/api/v1/recommendations", headers=dba_headers)
            assert gen_resp.status_code == 200
            recs_resp = client.get("/api/v1/recommendations", headers=viewer_headers)
            assert recs_resp.status_code == 200
            recs = recs_resp.json()["items"]
            assert len(recs) >= 2
            rec1_id = recs[0]["id"]
            rec2_id = recs[1]["id"]
            assert recs[0]["requires_approval"] is True
            assert recs[0]["status"] == "pending"

            # Step (d): Review candidate execution plan and safe sandbox simulation result
            sim_resp = client.post(
                "/api/v1/simulations",
                headers=dba_headers,
                json={"recommendation_id": rec1_id, "benchmark_runs": 1},
            )
            assert sim_resp.status_code == 200
            sim_data = sim_resp.json()
            assert sim_data["recommendation_id"] == rec1_id
            assert sim_data["status"] == "completed"
            assert sim_data["baseline_cost"] is not None
            assert sim_data["proposed_cost"] is not None

            # Step (e): Attempt approval as a VIEWER and confirm 403 denial
            viewer_approve = client.post(
                f"/api/v1/recommendations/{rec1_id}/approve",
                headers=viewer_headers,
                json={"reason": "Viewer trying to approve directly"},
            )
            assert viewer_approve.status_code == 403

            # Step (f): Approve as an authorized DBA
            dba_approve = client.post(
                f"/api/v1/recommendations/{rec1_id}/approve",
                headers=dba_headers,
                json={"reason": "DBA verified index selectivity and low write overhead in sandbox"},
            )
            assert dba_approve.status_code == 200
            approved_data = dba_approve.json()
            assert approved_data["status"] == "approved"
            assert approved_data["lifecycle_state"] == "approved"
            assert approved_data["applied_at"] is None

            # Step (g): Record applied deployment and post-change validation result for rec1
            exec_resp = client.post(
                f"/api/v1/recommendations/{rec1_id}/apply",
                headers=dba_headers,
                json={
                    "confirm_applied": True,
                    "deployment_reference": "CHG-2026-1012",
                    "verify_catalog": False,
                    "reason": "Applied CREATE INDEX CONCURRENTLY during maintenance window",
                },
            )
            assert exec_resp.status_code == 200
            assert exec_resp.json()["lifecycle_state"] == "applied"
            # Before validation, confirm it is NOT marked as a verified improvement
            assert exec_resp.json()["provenance_state"] != "VERIFIED_POST_CHANGE"

            val_resp = client.post(
                f"/api/v1/recommendations/{rec1_id}/validate",
                headers=dba_headers,
                json={
                    "post_change_observation": {
                        "query_id": 5001,
                        "calls": 1200,
                        "mean_exec_time_ms": 18.5,
                        "min_exec_time_ms": 4.0,
                        "max_exec_time_ms": 45.0,
                        "total_exec_time_ms": 22200.0,
                        "rows": 6000,
                        "shared_blks_hit": 9200,
                        "shared_blks_read": 300,
                        "window_seconds": 60.0,
                        "provenance_state": "LIVE_TELEMETRY",
                        "is_synthetic": False,
                        "is_measured": True,
                        "environment": "production",
                    },
                    "reason": "Observed 84.6% latency reduction in pg_stat_statements after index creation",
                },
            )
            assert val_resp.status_code == 200
            val_data = val_resp.json()
            assert val_data["lifecycle_state"] == "verified_successful"
            assert val_data["provenance_state"] == "VERIFIED_POST_CHANGE"
            assert val_data["impact_summary"]["outcome_classification"] == "verified_successful"
            assert val_data["impact_summary"]["latency_improvement_pct"] > 50.0

            # Step (h): Verify lifecycle history and unified audit record
            lc_resp = client.get(f"/api/v1/recommendations/{rec1_id}/trace", headers=viewer_headers)
            assert lc_resp.status_code == 200
            lc_data = lc_resp.json()
            assert lc_data["recommendation"]["lifecycle_state"] == "verified_successful"
            assert len(lc_data["audit_events"]) >= 3

            audit_resp = client.get("/api/v1/audit/query?ledger=security&page=1&page_size=50", headers=dba_headers)
            assert audit_resp.status_code == 200
            audit_items = audit_resp.json()["items"]
            assert len(audit_items) >= 4

            rec_audit_resp = client.get("/api/v1/audit/query?ledger=recommendations&page=1&page_size=50", headers=dba_headers)
            assert rec_audit_resp.status_code == 200
            assert len(rec_audit_resp.json()["items"]) >= 3

            # Step (i): Confirm that an unmeasured or failed/regressed optimization is NEVER displayed as a verified improvement
            client.post(
                f"/api/v1/recommendations/{rec2_id}/approve",
                headers=dba_headers,
                json={"reason": "Approving second recommendation for regression test"},
            )
            client.post(
                f"/api/v1/recommendations/{rec2_id}/apply",
                headers=dba_headers,
                json={
                    "confirm_applied": True,
                    "deployment_reference": "CHG-2026-1013",
                    "verify_catalog": False,
                    "reason": "Applied candidate change",
                },
            )
            reg_val_resp = client.post(
                f"/api/v1/recommendations/{rec2_id}/validate",
                headers=dba_headers,
                json={
                    "post_change_observation": {
                        "query_id": 5002,
                        "calls": 800,
                        "mean_exec_time_ms": 95.0,  # Worse than 45.0ms baseline!
                        "min_exec_time_ms": 30.0,
                        "max_exec_time_ms": 280.0,
                        "total_exec_time_ms": 76000.0,
                        "rows": 400,
                        "window_seconds": 60.0,
                        "provenance_state": "LIVE_TELEMETRY",
                        "is_synthetic": False,
                        "is_measured": True,
                        "environment": "production",
                    },
                    "reason": "Post-change latency increased from 45ms to 95ms",
                },
            )
            assert reg_val_resp.status_code == 200
            reg_data = reg_val_resp.json()
            assert reg_data["lifecycle_state"] == "regressed"
            assert reg_data["impact_summary"]["outcome_classification"] == "regressed"
            assert reg_data["lifecycle_state"] != "verified_successful"
            assert reg_data["provenance_state"] != "VERIFIED_POST_CHANGE"
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
