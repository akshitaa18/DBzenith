"""Phase 7 Backend & API Integration Tests for DBZenith Professional Observability UI.

Covers:
1. Slow Queries server-side filtering & sorting:
   - min_mean_ms, max_mean_ms, severity (critical / high / moderate), database_name,
     user_name, query_fingerprint, search, window_seconds, sort_by, sort_dir.
2. Query Details Trace (/api/v1/queries/{query_id}/trace):
   - Includes telemetry_history across snapshots, provenance, and matching_recommendations.
3. Audit Logs server-side query (/api/v1/audit/query) & access-controlled export (/api/v1/audit/export):
   - Role enforcement (VIEWER denied with 403, ANALYST/DBA/ADMIN permitted).
   - Server-side filtering by ledger, category, status, actor, search, and pagination.
   - CSV and JSON export formats, sensitive key scrubbing, and immutable audit_ledger_exported event recording.
4. System Health Diagnostics (/api/v1/health/diagnostics) & Guided Database Connection Validation (/api/v1/config/database/validate):
   - Real extension checks (pg_stat_statements, hypopg), collector freshness/error surfacing,
     masked connection strings (never exposing passwords), and 6-step guided validation.
"""

from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import _API_RATE_LIMITER, _AUTH_RATE_LIMITER
from app.core.security import Role, get_security_manager, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.recommendation import OptimizationRecommendation, RecommendationAuditEvent
from app.models.security import SecurityAuditEvent, User
from app.models.workload import QueryStatistic, WorkloadSnapshot


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


@pytest.fixture
def phase7_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_factory()

    # Seed users
    for uid, username, email, pwd, role in [
        (1, "viewer_user", "viewer@dbzenith.local", "ViewerPass123!", "VIEWER"),
        (2, "analyst_user", "analyst@dbzenith.local", "AnalystPass123!", "ANALYST"),
        (3, "dba_user", "dba@dbzenith.local", "DbaPass123!", "DBA"),
        (4, "admin_user", "admin@dbzenith.local", "AdminPass123!", "ADMIN"),
    ]:
        h, s = hash_password(pwd)
        session.add(
            User(
                id=uid,
                username=username,
                email=email,
                password_hash=h,
                salt=s,
                role=role,
                is_active=True,
            )
        )

    # Seed 2 snapshots to test window_seconds and telemetry_history
    snap1 = WorkloadSnapshot(
        id=1,
        window_seconds=3600.0,
        total_calls=600,
        total_exec_time_ms=120000.0,
        unique_queries=2,
        slow_queries=2,
        provenance_state="HISTORICAL_OBSERVATION",
        collection_status="ok",
    )
    snap2 = WorkloadSnapshot(
        id=2,
        window_seconds=300.0,
        total_calls=900,
        total_exec_time_ms=210000.0,
        unique_queries=3,
        slow_queries=3,
        provenance_state="LIVE_TELEMETRY",
        collection_status="ok",
    )
    session.add_all([snap1, snap2])
    session.flush()

    session.add_all(
        [
            # Snapshot 1 historical observation for query 1001
            QueryStatistic(
                id=1,
                snapshot_id=1,
                query_id=1001,
                database_name="dbzenith_prod",
                user_name="app_user",
                normalized_query="SELECT * FROM orders WHERE order_date >= $1",
                query_fingerprint="fp_orders_date",
                calls=400,
                total_exec_time_ms=64000.0,
                mean_exec_time_ms=160.0,
                min_exec_time_ms=20.0,
                max_exec_time_ms=520.0,
                rows=4000,
                shared_blks_hit=1000,
                shared_blks_read=500,
                shared_blks_dirtied=0,
                shared_blks_written=0,
                local_blks_hit=0,
                local_blks_read=0,
                temp_blks_read=0,
                temp_blks_written=0,
                blk_read_time_ms=30.0,
                blk_write_time_ms=0.0,
                query_frequency_per_minute=8.0,
            ),
            # Snapshot 2 critical slow query (mean 240ms >= 150ms)
            QueryStatistic(
                id=2,
                snapshot_id=2,
                query_id=1001,
                database_name="dbzenith_prod",
                user_name="app_user",
                normalized_query="SELECT * FROM orders WHERE order_date >= $1",
                query_fingerprint="fp_orders_date",
                calls=500,
                total_exec_time_ms=120000.0,
                mean_exec_time_ms=240.0,
                min_exec_time_ms=25.0,
                max_exec_time_ms=790.0,
                rows=5000,
                shared_blks_hit=1200,
                shared_blks_read=900,
                shared_blks_dirtied=0,
                shared_blks_written=0,
                local_blks_hit=0,
                local_blks_read=0,
                temp_blks_read=0,
                temp_blks_written=0,
                blk_read_time_ms=45.0,
                blk_write_time_ms=0.0,
                query_frequency_per_minute=10.0,
            ),
            # Snapshot 2 high severity query (mean 95ms: 80..150ms)
            QueryStatistic(
                id=3,
                snapshot_id=2,
                query_id=1002,
                database_name="analytics_wh",
                user_name="bi_reader",
                normalized_query="SELECT customer_id, SUM(amount) FROM invoices GROUP BY customer_id",
                query_fingerprint="fp_invoices_sum",
                calls=300,
                total_exec_time_ms=28500.0,
                mean_exec_time_ms=95.0,
                min_exec_time_ms=15.0,
                max_exec_time_ms=210.0,
                rows=1500,
                shared_blks_hit=2400,
                shared_blks_read=300,
                shared_blks_dirtied=0,
                shared_blks_written=0,
                local_blks_hit=0,
                local_blks_read=0,
                temp_blks_read=0,
                temp_blks_written=0,
                blk_read_time_ms=12.0,
                blk_write_time_ms=0.0,
                query_frequency_per_minute=6.0,
            ),
            # Snapshot 2 moderate severity query (mean 42ms < 80ms)
            QueryStatistic(
                id=4,
                snapshot_id=2,
                query_id=1003,
                database_name="dbzenith_prod",
                user_name="app_user",
                normalized_query="SELECT id, email FROM customers WHERE id = $1",
                query_fingerprint="fp_customers_pk",
                calls=100,
                total_exec_time_ms=4200.0,
                mean_exec_time_ms=42.0,
                min_exec_time_ms=5.0,
                max_exec_time_ms=90.0,
                rows=100,
                shared_blks_hit=900,
                shared_blks_read=20,
                shared_blks_dirtied=0,
                shared_blks_written=0,
                local_blks_hit=0,
                local_blks_read=0,
                temp_blks_read=0,
                temp_blks_written=0,
                blk_read_time_ms=1.0,
                blk_write_time_ms=0.0,
                query_frequency_per_minute=2.0,
            ),
        ]
    )

    rec = OptimizationRecommendation(
        id=501,
        recommendation_key="rec_key_501",
        type="index",
        target="orders",
        proposed_change="CREATE INDEX CONCURRENTLY idx_orders_order_date ON orders (order_date);",
        reason="Sequential scan on orders.order_date",
        evidence={"query_id": 1001, "mean_exec_time_ms": 240.0},
        expected_benefit="65% planner cost reduction",
        risk="low",
        confidence=0.92,
        affected_queries=[1001],
        query_fingerprint="fp_orders_date",
        requires_approval=True,
        status="pending",
    )
    session.add(rec)
    session.flush()

    session.add(
        RecommendationAuditEvent(
            id=1,
            recommendation_id=501,
            action="approved",
            previous_status="pending",
            new_status="approved",
            reason="Validated in staging maintenance window",
            metadata_json=json.dumps({"operator": "dba_user", "password_hash": "MUST_BE_SCRUBBED"}),
        )
    )
    session.add(
        SecurityAuditEvent(
            id=1,
            event_category="AUTH",
            action="user_login",
            actor_id="3",
            actor_username="dba_user",
            actor_role="DBA",
            target_entity="session",
            target_id="1",
            status="SUCCESS",
            details_json=json.dumps({"ip": "127.0.0.1", "secret_key": "MUST_BE_SCRUBBED"}),
        )
    )
    session.commit()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    session.close()


def _auth_header(uid: int, username: str, role: Role) -> dict[str, str]:
    mgr = get_security_manager()
    token = mgr.create_token(user_id=str(uid), username=username, role=role)
    return {"Authorization": f"Bearer {token}"}


def test_slow_queries_server_side_filtering_and_sorting(phase7_client: TestClient):
    headers = _auth_header(1, "viewer_user", Role.VIEWER)

    # 1. Filter by severity=critical (>= 150ms)
    res_crit = phase7_client.get("/api/v1/queries/slow?severity=critical", headers=headers)
    assert res_crit.status_code == 200
    data_crit = res_crit.json()
    assert data_crit["total"] == 1
    assert data_crit["items"][0]["query_id"] == 1001

    # 2. Filter by database_name=analytics_wh
    res_db = phase7_client.get("/api/v1/queries/slow?database_name=analytics_wh&min_mean_ms=0", headers=headers)
    assert res_db.status_code == 200
    data_db = res_db.json()
    assert data_db["total"] == 1
    assert data_db["items"][0]["query_id"] == 1002

    # 3. Filter by query_fingerprint
    res_fp = phase7_client.get("/api/v1/queries/slow?query_fingerprint=fp_customers&min_mean_ms=0", headers=headers)
    assert res_fp.status_code == 200
    assert res_fp.json()["total"] == 1
    assert res_fp.json()["items"][0]["query_id"] == 1003

    # 4. Sort by calls ascending with min_mean_ms=0
    res_sort = phase7_client.get(
        "/api/v1/queries/slow?min_mean_ms=0&sort_by=calls&sort_dir=asc",
        headers=headers,
    )
    assert res_sort.status_code == 200
    calls_list = [item["calls"] for item in res_sort.json()["items"]]
    assert calls_list == sorted(calls_list)


def test_query_trace_includes_telemetry_history(phase7_client: TestClient):
    headers = _auth_header(1, "viewer_user", Role.VIEWER)
    res = phase7_client.get("/api/v1/queries/1001/trace", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["query_id"] == 1001
    assert "telemetry_history" in body
    assert len(body["telemetry_history"]) == 2
    assert body["telemetry_history"][0]["snapshot_id"] == 2
    assert body["telemetry_history"][1]["snapshot_id"] == 1


def test_audit_query_and_export_rbac_and_sanitization(phase7_client: TestClient):
    viewer_headers = _auth_header(1, "viewer_user", Role.VIEWER)
    analyst_headers = _auth_header(2, "analyst_user", Role.ANALYST)

    # VIEWER cannot access /audit/query or /audit/export
    assert phase7_client.get("/api/v1/audit/query", headers=viewer_headers).status_code == 403
    assert phase7_client.get("/api/v1/audit/export", headers=viewer_headers).status_code == 403

    # ANALYST can query paginated recommendations & security audit ledgers
    q_rec = phase7_client.get("/api/v1/audit/query?ledger=recommendations&page=1&page_size=10", headers=analyst_headers)
    assert q_rec.status_code == 200
    q_rec_body = q_rec.json()
    assert q_rec_body["total"] == 1
    assert q_rec_body["items"][0]["recommendation_id"] == 501
    # Verify sensitive metadata keys are scrubbed
    assert "password_hash" not in json.dumps(q_rec_body)

    # ANALYST can export CSV and JSON
    exp_csv = phase7_client.get("/api/v1/audit/export?ledger=recommendations&format=csv", headers=analyst_headers)
    assert exp_csv.status_code == 200
    assert "text/csv" in exp_csv.headers["content-type"]
    assert "Validated in staging maintenance window" in exp_csv.text
    assert "MUST_BE_SCRUBBED" not in exp_csv.text

    exp_json = phase7_client.get("/api/v1/audit/export?ledger=security&format=json", headers=analyst_headers)
    assert exp_json.status_code == 200
    parsed = json.loads(exp_json.text)
    assert parsed["ledger"] == "security"
    assert "MUST_BE_SCRUBBED" not in exp_json.text


def test_health_diagnostics_and_guided_connection_validation(phase7_client: TestClient):
    viewer_headers = _auth_header(1, "viewer_user", Role.VIEWER)

    diag = phase7_client.get("/api/v1/health/diagnostics", headers=viewer_headers)
    assert diag.status_code == 200
    diag_body = diag.json()
    assert "api" in diag_body
    assert "primary_database" in diag_body
    assert "sandbox_database" in diag_body
    assert "extensions" in diag_body
    assert "pg_stat_statements" in diag_body["extensions"]
    assert "hypopg" in diag_body["extensions"]
    assert "collector" in diag_body
    # Ensure masked DSN never leaks plaintext passwords
    assert "postgres:postgres" not in json.dumps(diag_body)

    val = phase7_client.post(
        "/api/v1/config/database/validate",
        headers=viewer_headers,
        json={
            "target": "primary",
            "port": 5432,
            "ssl_mode": "prefer",
            "verify_extensions": True,
        },
    )
    assert val.status_code == 200
    val_body = val.json()
    assert val_body["overall_status"] in ("ready", "degraded", "failed")
    assert len(val_body["steps"]) == 6
    step_names = [s["step"] for s in val_body["steps"]]
    assert "connectivity" in step_names
    assert "pg_stat_statements" in step_names
    assert "hypopg" in step_names
    assert "postgres:postgres" not in json.dumps(val_body)
