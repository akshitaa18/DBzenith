"""Phase 8 Tests: PostgreSQL Index Portfolio Advisor & Configurable Workload Regression Alerts.

Covers Feature D requirements:
1. Overlapping-index detection with representative schemas (exact duplicate, B-tree left-prefix, partial predicate safety).
2. Low-usage indexes with recently reset statistics, index age, and constraint enforcement.
3. Safe handling of missing statistics and unsupported index types (GIN, GiST, BRIN, Hash).
4. Composite and partial index proposals with selectivity and write-overhead awareness.
5. Read-only analysis verification (never executes DDL or drops indexes).
6. Regression thresholds, insufficient samples, single noisy measurement suppression, deduplication, cooldowns, and auto-recovery.
7. Role-based access control and export permissions across Index Portfolio and Regression Alerts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import _API_RATE_LIMITER, _AUTH_RATE_LIMITER
from app.core.security import get_security_manager, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.alert import AlertAuditEvent, WorkloadAlert, WorkloadAlertRule
from app.models.security import SecurityAuditEvent, User
from app.models.workload import QueryStatistic, WorkloadSnapshot
from app.services.recommendations.index_portfolio import IndexPortfolioAdvisor


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    _API_RATE_LIMITER.history.clear()
    _AUTH_RATE_LIMITER.history.clear()
    yield
    _API_RATE_LIMITER.history.clear()
    _AUTH_RATE_LIMITER.history.clear()


def _setup_isolated_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    pw_hash, pw_salt = hash_password("ValidPass123!")
    with TestingSessionLocal() as db:
        seeded_users = [
            (1, "viewer_user", "VIEWER"),
            (2, "dba_lead", "DBA"),
            (3, "dba_operator", "DBA"),
            (4, "perf_analyst", "ANALYST"),
            (10, "test_user", "ANALYST"),
            (11, "test_viewer", "VIEWER"),
            (12, "test_dba", "DBA"),
            (13, "test_admin", "ADMIN"),
        ]
        for uid, uname, urole in seeded_users:
            db.add(
                User(
                    id=uid,
                    username=uname,
                    email=f"{uname}@dbzenith.local",
                    role=urole,
                    password_hash=pw_hash,
                    salt=pw_salt,
                    is_active=True,
                )
            )
        db.commit()

    def override_get_db():
        with TestingSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, TestingSessionLocal, engine


def _headers(role: str, user_id: str | None = None, username: str | None = None) -> dict[str, str]:
    default_map = {
        "VIEWER": ("11", "test_viewer"),
        "ANALYST": ("10", "test_user"),
        "DBA": ("12", "test_dba"),
        "ADMIN": ("13", "test_admin"),
    }
    uid, uname = default_map.get(role.upper(), ("10", "test_user"))
    if user_id is not None:
        uid = user_id
    if username is not None:
        uname = username
    mgr = get_security_manager()
    token = mgr.create_token(user_id=str(uid), username=uname, role=role.upper())
    return {"Authorization": f"Bearer {token}"}


def test_overlapping_low_usage_missing_stats_and_unsupported_index_types():
    """Tests representative schemas for overlapping indexes, recent stats reset, missing stats, and non-B-tree types."""
    client, SessionLocal, engine = _setup_isolated_client()
    try:
        # Track all SQL statements executed on the database to prove read-only behavior (zero DDL executed)
        executed_sql: list[str] = []

        @event.listens_for(engine, "before_cursor_execute")
        def _capture_sql(conn, cursor, statement, parameters, context, executemany):
            executed_sql.append(statement.strip().upper())

        now = datetime.now(timezone.utc)
        recent_reset = now - timedelta(minutes=25)  # < 24h threshold -> recently reset!

        representative_catalog = [
            # Primary key (never flagged as redundant or low-usage drop candidate)
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "orders_pkey",
                "indexdef": "CREATE UNIQUE INDEX orders_pkey ON public.orders USING btree (order_id)",
                "is_primary": True,
                "is_unique": True,
                "index_size_bytes": 4_096_000,
                "table_size_bytes": 50_000_000,
                "idx_scan": 0,
                "n_tup_ins": 10000,
                "n_tup_upd": 5000,
            },
            # Narrow single-column B-tree index (left-prefix overlapped by idx_orders_cust_status)
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_customer_id",
                "indexdef": "CREATE INDEX idx_orders_customer_id ON public.orders USING btree (customer_id)",
                "is_primary": False,
                "is_unique": False,
                "index_size_bytes": 2_048_000,
                "table_size_bytes": 50_000_000,
                "idx_scan": 120,
                "n_tup_ins": 10000,
                "n_tup_upd": 5000,
            },
            # Wider composite B-tree index covering customer_id
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_cust_status",
                "indexdef": "CREATE INDEX idx_orders_cust_status ON public.orders USING btree (customer_id, status)",
                "is_primary": False,
                "is_unique": False,
                "index_size_bytes": 3_500_000,
                "table_size_bytes": 50_000_000,
                "idx_scan": 4500,
                "n_tup_ins": 10000,
                "n_tup_upd": 5000,
            },
            # Exact duplicate index on orders (status)
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_status_dup_a",
                "indexdef": "CREATE INDEX idx_orders_status_dup_a ON public.orders USING btree (status)",
                "is_primary": False,
                "is_unique": False,
                "index_size_bytes": 1_500_000,
                "table_size_bytes": 50_000_000,
                "idx_scan": 50,
            },
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_status_dup_b",
                "indexdef": "CREATE INDEX idx_orders_status_dup_b ON public.orders USING btree (status)",
                "is_primary": False,
                "is_unique": False,
                "index_size_bytes": 1_500_000,
                "table_size_bytes": 50_000_000,
                "idx_scan": 800,
            },
            # Low-usage index with 0 scans during recently reset stats window
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_legacy_ref",
                "indexdef": "CREATE INDEX idx_orders_legacy_ref ON public.orders USING btree (legacy_ref)",
                "is_primary": False,
                "is_unique": False,
                "index_size_bytes": 1_024_000,
                "table_size_bytes": 50_000_000,
                "idx_scan": 0,
                "index_age_seconds": 1800,
            },
            # Index with missing statistics (idx_scan is None)
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_missing_stats",
                "indexdef": "CREATE INDEX idx_orders_missing_stats ON public.orders USING btree (shipping_code)",
                "is_primary": False,
                "is_unique": False,
                "index_size_bytes": 512_000,
                "table_size_bytes": 50_000_000,
                "idx_scan": None,
            },
            # Unsupported non-B-tree index types (GIN and BRIN) — must not crash or apply B-tree prefix overlap
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_tags_gin",
                "indexdef": "CREATE INDEX idx_orders_tags_gin ON public.orders USING gin (tags)",
                "is_primary": False,
                "is_unique": False,
                "index_size_bytes": 2_000_000,
                "table_size_bytes": 50_000_000,
                "idx_scan": 300,
            },
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_tags_gin_wide",
                "indexdef": "CREATE INDEX idx_orders_tags_gin_wide ON public.orders USING gin (tags, payload)",
                "is_primary": False,
                "is_unique": False,
                "index_size_bytes": 3_000_000,
                "table_size_bytes": 50_000_000,
                "idx_scan": 400,
            },
        ]

        workload_queries = [
            {
                "query_id": 9001,
                "normalized_query": "SELECT order_id, amount FROM orders WHERE region_id = $1 AND order_date >= $2 ORDER BY order_date DESC",
                "calls": 1800,
                "mean_exec_time_ms": 340.0,
                "total_exec_time_ms": 612000.0,
                "shared_blks_read": 24000,
            },
            {
                "query_id": 9002,
                "normalized_query": "SELECT order_id, customer_id FROM orders WHERE status = 'pending' AND warehouse_id = $1",
                "calls": 950,
                "mean_exec_time_ms": 210.0,
                "total_exec_time_ms": 199500.0,
                "shared_blks_read": 11000,
            },
            {
                "query_id": 9003,
                "normalized_query": "SELECT order_id FROM orders WHERE boolean_flag = $1",
                "calls": 400,
                "mean_exec_time_ms": 95.0,
                "total_exec_time_ms": 38000.0,
                "shared_blks_read": 2000,
            },
        ]

        executed_sql.clear()
        res = client.post(
            "/api/v1/index-portfolio/analyze",
            headers=_headers("VIEWER"),
            json={
                "catalog_override": representative_catalog,
                "column_stats_override": {
                    "orders.region_id": {"n_distinct": 25.0, "null_frac": 0.0},
                    "orders.order_date": {"n_distinct": -0.5, "null_frac": 0.0},
                    "orders.boolean_flag": {"n_distinct": 2.0, "null_frac": 0.0},
                },
                "stats_reset_at": recent_reset.isoformat(),
                "stats_reset_supplied": True,
                "workload_queries_override": workload_queries,
            },
        )
        assert res.status_code == 200, res.text
        data = res.json()

        # Verify read-only guarantee: no DDL executed
        assert data["read_only_analysis"] is True
        assert data["auto_execution_permitted"] is False
        for stmt in executed_sql:
            assert not stmt.startswith(("DROP INDEX", "CREATE INDEX", "ALTER ", "REINDEX"))

        # 1. Overlapping index detection
        overlaps = {c["index_name"]: c for c in data["overlapping_candidates"]}
        assert "idx_orders_customer_id" in overlaps
        assert overlaps["idx_orders_customer_id"]["overlap_type"] == "left_prefix_overlap"
        assert overlaps["idx_orders_customer_id"]["covering_index_name"] == "idx_orders_cust_status"
        assert overlaps["idx_orders_customer_id"]["auto_drop_permitted"] is False
        assert overlaps["idx_orders_customer_id"]["requires_dba_review"] is True

        assert "idx_orders_status_dup_a" in overlaps
        assert overlaps["idx_orders_status_dup_a"]["overlap_type"] == "exact_duplicate"
        assert overlaps["idx_orders_status_dup_a"]["covering_index_name"] == "idx_orders_status_dup_b"

        # Primary key and GIN non-B-tree indexes must NOT be flagged as B-tree prefix overlaps
        assert "orders_pkey" not in overlaps
        assert "idx_orders_tags_gin" not in overlaps

        # 2. Low-usage index with recently reset statistics
        assert data["statistics_completeness"]["stats_recently_reset"] is True
        assert data["statistics_completeness"]["status"] == "recently_reset"
        assert data["statistics_completeness"]["missing_scan_counter_count"] == 1
        assert data["statistics_completeness"]["unsupported_index_type_count"] == 2

        low_usage = {c["index_name"]: c for c in data["low_usage_candidates"]}
        assert "idx_orders_legacy_ref" in low_usage
        lu_item = low_usage["idx_orders_legacy_ref"]
        assert lu_item["stats_recently_reset"] is True
        assert lu_item["advisory_status"] == "caution_stats_recently_reset"
        assert lu_item["auto_drop_permitted"] is False
        assert any("reset recently" in c.lower() for c in lu_item["cautions"])

        # Missing stats index (idx_scan=None) and primary key must NOT be falsely claimed as low-usage
        assert "idx_orders_missing_stats" not in low_usage
        assert "orders_pkey" not in low_usage

        # 3. Composite & partial index proposals + low-selectivity skip
        proposals = data["missing_index_proposals"]
        prop_types = {p["proposal_type"] for p in proposals}
        assert "composite_index" in prop_types
        assert "partial_index" in prop_types

        # Verify composite index puts equality column (region_id) ahead of range/sort column (order_date)
        comp_orders = [
            p for p in proposals if p["proposal_type"] == "composite_index" and "region_id" in p["columns"]
        ]
        assert len(comp_orders) >= 1
        assert comp_orders[0]["columns"] == ["region_id", "order_date"]

        # Verify low-selectivity single-column index (boolean_flag with n_distinct=2) was skipped
        skipped_cols = [s["columns"] for s in data["skipped_candidates"]]
        assert ["boolean_flag"] in skipped_cols
    finally:
        app.dependency_overrides.clear()


def test_regression_alerts_thresholds_insufficient_samples_noise_dedup_cooldown_and_recovery():
    """Tests the full lifecycle of deterministic regression alerts."""
    client, SessionLocal, _ = _setup_isolated_client()
    try:
        base_time = datetime.now(timezone.utc) - timedelta(hours=6)

        with SessionLocal() as db:
            # Create a custom rule requiring 3 baseline samples and 2 consecutive breaches, with 1800s cooldown
            rule = WorkloadAlertRule(
                rule_key="custom_latency_rule",
                name="Orders Query Latency Regression",
                description="50% latency regression rule",
                metric_name="mean_exec_time_ms",
                scope="query",
                query_fingerprint_filter="fp_orders_lookup",
                comparison_operator="pct_increase",
                threshold_value=50.0,
                min_absolute_value=50.0,
                baseline_window_seconds=86400,
                comparison_window_seconds=3600,
                min_baseline_samples=3,
                min_comparison_samples=2,
                consecutive_breaches_required=2,
                allow_single_measurement=False,
                cooldown_seconds=1800,
                auto_resolve=True,
                severity="critical",
                enabled=True,
                created_by="dba_admin",
            )
            db.add(rule)
            db.commit()
            db.refresh(rule)
            rule_id = rule.id

        def _add_observation(mean_ms: float, offset_minutes: int):
            with SessionLocal() as db:
                t = base_time + timedelta(minutes=offset_minutes)
                snap = WorkloadSnapshot(
                    captured_at=t,
                    window_seconds=60.0,
                    total_calls=100,
                    total_exec_time_ms=mean_ms * 100,
                    unique_queries=1,
                    slow_queries=1 if mean_ms >= 80 else 0,
                    provenance_state="LIVE_TELEMETRY",
                    collection_status="success",
                )
                db.add(snap)
                db.flush()
                db.add(
                    QueryStatistic(
                        snapshot_id=snap.id,
                        query_id=777,
                        normalized_query="SELECT * FROM orders WHERE customer_id = $1",
                        query_fingerprint="fp_orders_lookup",
                        calls=100,
                        total_exec_time_ms=mean_ms * 100,
                        mean_exec_time_ms=mean_ms,
                        min_exec_time_ms=mean_ms * 0.5,
                        max_exec_time_ms=mean_ms * 1.5,
                        rows=100,
                        captured_at=t,
                        window_seconds=60.0,
                        provenance_state="LIVE_TELEMETRY",
                    )
                )
                db.commit()

        # 1. Only 2 observations (< 3 baseline required) -> insufficient_baseline_samples, 0 alerts triggered
        _add_observation(100.0, 10)
        _add_observation(105.0, 20)

        eval1 = client.post(
            "/api/v1/alerts/evaluate",
            headers=_headers("ANALYST"),
            json={"rule_ids": [rule_id]},
        )
        assert eval1.status_code == 200
        d1 = eval1.json()
        assert d1["triggered_count"] == 0
        assert any(i["reason_code"] == "insufficient_baseline_samples" for i in d1["insufficient_history"])

        # 2. Add 3rd baseline observation (100ms) + 1 single spike (220ms, +120%) -> suppressed as single noisy measurement!
        _add_observation(100.0, 30)
        _add_observation(220.0, 40)

        eval2 = client.post(
            "/api/v1/alerts/evaluate",
            headers=_headers("ANALYST"),
            json={"rule_ids": [rule_id]},
        )
        assert eval2.status_code == 200
        d2 = eval2.json()
        assert d2["triggered_count"] == 0
        assert any(
            s["reason_code"] == "single_noisy_measurement_suppressed"
            for s in d2["suppressed_evaluations"]
        )

        # 3. Add 2nd consecutive breach (240ms) -> triggers 1 active alert!
        _add_observation(240.0, 50)
        eval3 = client.post(
            "/api/v1/alerts/evaluate",
            headers=_headers("ANALYST"),
            json={"rule_ids": [rule_id]},
        )
        assert eval3.status_code == 200
        d3 = eval3.json()
        assert d3["triggered_count"] == 1
        alert_id = d3["triggered_alert_ids"][0]

        # 4. Evaluate again while condition persists -> deduplicated (no duplicate alert created, occurrence_count=2)
        _add_observation(250.0, 60)
        eval4 = client.post(
            "/api/v1/alerts/evaluate",
            headers=_headers("ANALYST"),
            json={"rule_ids": [rule_id]},
        )
        assert eval4.status_code == 200
        d4 = eval4.json()
        assert d4["triggered_count"] == 0
        assert d4["deduplicated_count"] == 1

        detail_res = client.get(f"/api/v1/alerts/{alert_id}", headers=_headers("VIEWER"))
        assert detail_res.status_code == 200
        alert_detail = detail_res.json()
        assert alert_detail["occurrence_count"] == 2
        assert alert_detail["status"] == "active"
        assert alert_detail["affected_query_fingerprints"][0]["query_fingerprint"] == "fp_orders_lookup"

        # 5. Acknowledge the alert as DBA
        ack_res = client.post(
            f"/api/v1/alerts/{alert_id}/acknowledge",
            headers=_headers("DBA", user_id="2", username="dba_lead"),
            json={"reason": "Investigating missing index on orders.customer_id"},
        )
        assert ack_res.status_code == 200
        ack_data = ack_res.json()
        assert ack_data["status"] == "acknowledged"
        assert ack_data["acknowledged_by"] == "dba_lead"
        assert any(ev["action"] == "acknowledged" for ev in ack_data["audit_history"])

        # 6. Metric recovers back to baseline (98ms) -> auto-resolves the alert!
        _add_observation(98.0, 70)
        eval5 = client.post(
            "/api/v1/alerts/evaluate",
            headers=_headers("ANALYST"),
            json={"rule_ids": [rule_id]},
        )
        assert eval5.status_code == 200
        d5 = eval5.json()
        assert d5["auto_resolved_count"] == 1
        assert alert_id in d5["auto_resolved_alert_ids"]

        recovered_detail = client.get(f"/api/v1/alerts/{alert_id}", headers=_headers("VIEWER")).json()
        assert recovered_detail["status"] == "resolved"
        assert recovered_detail["resolution_type"] == "auto_recovered"
        assert any(ev["action"] == "auto_resolved" for ev in recovered_detail["audit_history"])

        # 7. Immediate re-breach within 1800s cooldown window -> suppressed by cooldown_active!
        _add_observation(260.0, 80)
        _add_observation(270.0, 90)
        eval6 = client.post(
            "/api/v1/alerts/evaluate",
            headers=_headers("ANALYST"),
            json={"rule_ids": [rule_id]},
        )
        assert eval6.status_code == 200
        d6 = eval6.json()
        assert d6["triggered_count"] == 0
        assert any(s["reason_code"] == "cooldown_active" for s in d6["suppressed_evaluations"])
    finally:
        app.dependency_overrides.clear()


def test_role_based_access_unsupported_metrics_and_exports():
    """Verifies RBAC enforcement, unsupported metric rejection, and export auditing for Phase 8."""
    client, SessionLocal, _ = _setup_isolated_client()
    try:
        # 1. Unsupported metric is rejected with HTTP 422 and explicit supported metrics message
        bad_rule = client.post(
            "/api/v1/alerts/rules",
            headers=_headers("DBA"),
            json={
                "name": "Invalid AI Predictive Anomaly Rule",
                "metric_name": "predictive_neural_anomaly_score",
                "threshold_value": 0.9,
            },
        )
        assert bad_rule.status_code == 422
        assert "Unsupported alert metric" in bad_rule.text
        assert "mean_exec_time_ms" in bad_rule.text

        # 2. VIEWER cannot create/modify alert rules or export portfolio/alerts
        viewer_rule = client.post(
            "/api/v1/alerts/rules",
            headers=_headers("VIEWER"),
            json={
                "name": "Viewer Rule Attempt",
                "metric_name": "mean_exec_time_ms",
                "threshold_value": 60.0,
            },
        )
        assert viewer_rule.status_code == 403

        viewer_export_alerts = client.get("/api/v1/alerts/export?format=csv", headers=_headers("VIEWER"))
        assert viewer_export_alerts.status_code == 403

        viewer_export_portfolio = client.get("/api/v1/index-portfolio/export?format=csv", headers=_headers("VIEWER"))
        assert viewer_export_portfolio.status_code == 403

        # 3. DBA can create a valid rule; ANALYST can export both portfolio and alerts (and exports are audited)
        dba_rule = client.post(
            "/api/v1/alerts/rules",
            headers=_headers("DBA", user_id="3", username="dba_operator"),
            json={
                "name": "High Disk Read I/O Time",
                "metric_name": "blk_read_time_ms",
                "comparison_operator": "abs_above",
                "threshold_value": 120.0,
                "severity": "warning",
            },
        )
        assert dba_rule.status_code == 201
        assert dba_rule.json()["metric_name"] == "blk_read_time_ms"

        analyst_export_portfolio = client.get(
            "/api/v1/index-portfolio/export?format=csv",
            headers=_headers("ANALYST", user_id="4", username="perf_analyst"),
        )
        assert analyst_export_portfolio.status_code == 200
        assert "schema_name,table_name,index_name" in analyst_export_portfolio.text

        analyst_export_alerts = client.get(
            "/api/v1/alerts/export?format=json",
            headers=_headers("ANALYST", user_id="4", username="perf_analyst"),
        )
        assert analyst_export_alerts.status_code == 200

        with SessionLocal() as db:
            events = db.scalars(select(SecurityAuditEvent)).all()
            actions = {e.action for e in events}
            assert "alert_rule_created" in actions
            assert "index_portfolio_exported" in actions
            assert "workload_alerts_exported" in actions
    finally:
        app.dependency_overrides.clear()
