"""Phase 4: Data Provenance and Telemetry Transparency Test Suite.

Verifies all 6 required provenance invariants:
1. Synthetic records always display as demo data (SYNTHETIC_DEMO / DEMO).
2. Live observations display their real collection timestamp (LIVE_TELEMETRY / LIVE).
3. Missing collection times do not display as current (captured_at=None -> HISTORICAL_OBSERVATION / HISTORICAL, is_stale=True).
4. Hypothetical plan estimates cannot appear as verified speedups (HYPOTHETICAL_PLAN_ESTIMATE / ESTIMATED, is_measured=False, is_verified_speedup=False).
5. Stale telemetry triggers an appropriate warning (HISTORICAL_OBSERVATION / HISTORICAL, is_stale=True, staleness_warning populated).
6. Re-running demo initialization preserves unrelated legitimate data (snapshots, queries, recommendations, simulations, audit events) and respects ENABLE_DEMO_SEED.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import _API_RATE_LIMITER, _AUTH_RATE_LIMITER
from app.core.config import get_settings
from app.core.provenance import (
    ProvenanceBadgeLabel,
    ProvenanceState,
    compute_query_fingerprint,
    ensure_provenance_schema,
    resolve_observation_provenance,
    sanitize_collection_error,
    sanitize_source_identifier,
)
from app.core.security import Role, get_security_manager, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.plan import PlanAnalysis
from app.models.recommendation import OptimizationRecommendation, RecommendationAuditEvent
from app.models.security import SecurityAuditEvent, User
from app.models.simulation import OptimizationSimulation
from app.models.workload import QueryStatistic, WorkloadSnapshot
from app.services.workload.generator import auto_seed_if_empty, generate_comprehensive_workload


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
def prov_db():
    """Creates an isolated in-memory SQLite database for Phase 4 provenance testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ensure_provenance_schema(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = session_factory()

    pwd_hash, pwd_salt = hash_password("DbaPass123!")
    db.add(
        User(
            id=1,
            username="dba_prov",
            email="dba_prov@dbzenith.internal",
            password_hash=pwd_hash,
            salt=pwd_salt,
            role="DBA",
            is_active=True,
        )
    )
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield db
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()


@pytest.fixture
def dba_headers() -> dict[str, str]:
    token = get_security_manager().create_token(
        user_id="1",
        username="dba_prov",
        role=Role.DBA,
    )
    return {"Authorization": f"Bearer {token}"}


def test_source_and_error_sanitization_strips_credentials():
    """Verifies connection strings and collection errors never persist passwords or secrets."""
    raw_dsn = "postgresql+psycopg2://dbadmin:SuperSecretPass99!@db.production.internal:5432/analytics_prod"
    sanitized = sanitize_source_identifier(raw_dsn)
    assert "SuperSecretPass99" not in sanitized
    assert "dbadmin" not in sanitized
    assert sanitized == "postgresql://db.production.internal:5432/analytics_prod"

    raw_err = "FATAL: password authentication failed for user \"admin\" with password='MyPassword123' at postgresql://admin:MyPassword123@localhost:5432/db"
    clean_err = sanitize_collection_error(raw_err)
    assert clean_err is not None
    assert "MyPassword123" not in clean_err


def test_case_1_synthetic_records_always_display_as_demo_data(prov_db: Session, dba_headers: dict[str, str]):
    """Case 1: Synthetic records always display as demo data across workload, queries, recommendations, and simulations."""
    client = TestClient(app)

    res = client.post("/api/v1/workload/seed-demo", headers=dba_headers)
    assert res.status_code == 200
    seed_payload = res.json()
    assert seed_payload["provenance_state"] == ProvenanceState.SYNTHETIC_DEMO.value
    assert seed_payload["provenance_badge"] == ProvenanceBadgeLabel.DEMO.value
    assert seed_payload["is_synthetic"] is True

    # Workload summary must report DEMO and demo_mode_active=True
    summary_res = client.get("/api/v1/workload/summary", headers=dba_headers)
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["provenance_state"] == ProvenanceState.SYNTHETIC_DEMO.value
    assert summary["provenance_badge"] == ProvenanceBadgeLabel.DEMO.value
    assert summary["is_synthetic"] is True
    assert summary["is_measured"] is False
    assert summary["demo_mode_active"] is True
    assert summary["source_identifier"] == "synthetic://demo-workload-generator"
    assert len(summary["top_queries"]) > 0
    for tq in summary["top_queries"]:
        assert tq["provenance_state"] == ProvenanceState.SYNTHETIC_DEMO.value
        assert tq["provenance_badge"] == ProvenanceBadgeLabel.DEMO.value
        assert tq["is_synthetic"] is True
        assert tq["query_fingerprint"]

    # Slow queries must report DEMO
    slow_res = client.get("/api/v1/queries/slow?min_mean_ms=10", headers=dba_headers)
    assert slow_res.status_code == 200
    slow_items = slow_res.json()["items"]
    assert len(slow_items) > 0
    for q in slow_items:
        assert q["provenance_state"] == ProvenanceState.SYNTHETIC_DEMO.value
        assert q["provenance_badge"] == ProvenanceBadgeLabel.DEMO.value
        assert q["is_synthetic"] is True
        assert q["is_measured"] is False

    # Recommendations must report DEMO
    rec_res = client.get("/api/v1/recommendations", headers=dba_headers)
    assert rec_res.status_code == 200
    rec_items = rec_res.json()["items"]
    assert len(rec_items) > 0
    for rec in rec_items:
        assert rec["provenance_state"] == ProvenanceState.SYNTHETIC_DEMO.value
        assert rec["provenance_badge"] == ProvenanceBadgeLabel.DEMO.value
        assert rec["is_synthetic"] is True
        assert rec["is_measured"] is False

    # Simulations must report DEMO
    sim_res = client.get("/api/v1/simulations", headers=dba_headers)
    assert sim_res.status_code == 200
    sim_items = sim_res.json()
    assert len(sim_items) > 0
    for sim in sim_items:
        assert sim["provenance_state"] == ProvenanceState.SYNTHETIC_DEMO.value
        assert sim["provenance_badge"] == ProvenanceBadgeLabel.DEMO.value
        assert sim["is_synthetic"] is True
        assert sim["is_measured"] is False
        assert sim["is_verified_speedup"] is False


def test_case_2_live_observations_display_real_collection_timestamp(prov_db: Session, dba_headers: dict[str, str]):
    """Case 2: Live observations display their real collection timestamp and LIVE badge."""
    client = TestClient(app)
    real_captured_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    expected_iso_prefix = real_captured_at.strftime("%Y-%m-%dT%H:%M:%S")

    snap = WorkloadSnapshot(
        captured_at=real_captured_at,
        window_seconds=60.0,
        total_calls=420,
        total_exec_time_ms=12850.5,
        unique_queries=1,
        slow_queries=1,
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgresql://prod-db:5432/orders_db",
        collection_status="success",
        collection_error=None,
        is_synthetic=False,
        is_measured=True,
    )
    prov_db.add(snap)
    prov_db.flush()

    q_stat = QueryStatistic(
        snapshot_id=snap.id,
        query_id=910001,
        database_name="orders_db",
        user_name="app_service",
        normalized_query="SELECT id, total FROM orders WHERE customer_id = $1",
        calls=420,
        total_exec_time_ms=12850.5,
        mean_exec_time_ms=215.4,
        min_exec_time_ms=12.0,
        max_exec_time_ms=890.0,
        rows=420,
        shared_blks_hit=8400,
        shared_blks_read=620,
        shared_blks_dirtied=0,
        shared_blks_written=0,
        local_blks_hit=0,
        local_blks_read=0,
        temp_blks_read=0,
        temp_blks_written=0,
        blk_read_time_ms=45.2,
        blk_write_time_ms=0.0,
        query_frequency_per_minute=420.0,
        predicate_info={"table": "orders", "columns": ["customer_id"]},
        explain_plan=None,
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgresql://prod-db:5432/orders_db",
        query_fingerprint=compute_query_fingerprint("SELECT id, total FROM orders WHERE customer_id = $1"),
        captured_at=real_captured_at,
        window_seconds=60.0,
        is_synthetic=False,
        is_measured=True,
    )
    prov_db.add(q_stat)
    prov_db.commit()

    summary_res = client.get("/api/v1/workload/summary", headers=dba_headers)
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["provenance_state"] == ProvenanceState.LIVE_TELEMETRY.value
    assert summary["provenance_badge"] == ProvenanceBadgeLabel.LIVE.value
    assert summary["is_synthetic"] is False
    assert summary["is_measured"] is True
    assert summary["is_stale"] is False
    assert summary["demo_mode_active"] is False
    assert summary["source_identifier"] == "postgresql://prod-db:5432/orders_db"
    assert summary["captured_at"] is not None
    assert summary["captured_at"].startswith(expected_iso_prefix)

    detail_res = client.get("/api/v1/queries/910001", headers=dba_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["provenance_state"] == ProvenanceState.LIVE_TELEMETRY.value
    assert detail["provenance_badge"] == ProvenanceBadgeLabel.LIVE.value
    assert detail["is_synthetic"] is False
    assert detail["is_measured"] is True
    assert detail["is_stale"] is False
    assert detail["captured_at"].startswith(expected_iso_prefix)


def test_case_3_missing_collection_times_do_not_display_as_current(prov_db: Session, dba_headers: dict[str, str]):
    """Case 3: Missing collection times (captured_at=None) never display as current/LIVE."""
    client = TestClient(app)

    # First verify empty workload summary does not fabricate a current timestamp
    empty_res = client.get("/api/v1/workload/summary", headers=dba_headers)
    assert empty_res.status_code == 200
    empty_summary = empty_res.json()
    assert empty_summary["captured_at"] is None
    assert empty_summary["provenance_state"] == ProvenanceState.HISTORICAL_OBSERVATION.value
    assert empty_summary["provenance_badge"] == ProvenanceBadgeLabel.HISTORICAL.value
    assert empty_summary["is_stale"] is True
    assert empty_summary["staleness_warning"] is not None

    # Also verify a snapshot & QueryStatistic whose collection timestamp is NULL resolves to HISTORICAL, captured_at=None
    snap_no_ts = WorkloadSnapshot(
        window_seconds=60.0,
        total_calls=55,
        total_exec_time_ms=9900.0,
        unique_queries=1,
        slow_queries=1,
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgresql://prod-db:5432/orders_db",
        collection_status="success",
        is_synthetic=False,
        is_measured=True,
    )
    prov_db.add(snap_no_ts)
    prov_db.flush()
    prov_db.execute(text("UPDATE workload_snapshots SET captured_at = NULL WHERE id = :id"), {"id": snap_no_ts.id})

    orphan_q = QueryStatistic(
        snapshot_id=snap_no_ts.id,
        query_id=920002,
        database_name="orders_db",
        user_name="app_service",
        normalized_query="SELECT * FROM invoices WHERE status = $1",
        calls=55,
        total_exec_time_ms=9900.0,
        mean_exec_time_ms=180.0,
        min_exec_time_ms=50.0,
        max_exec_time_ms=400.0,
        rows=55,
        shared_blks_hit=100,
        shared_blks_read=50,
        shared_blks_dirtied=0,
        shared_blks_written=0,
        local_blks_hit=0,
        local_blks_read=0,
        temp_blks_read=0,
        temp_blks_written=0,
        blk_read_time_ms=10.0,
        blk_write_time_ms=0.0,
        query_frequency_per_minute=55.0,
        predicate_info=None,
        explain_plan=None,
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgresql://prod-db:5432/orders_db",
        captured_at=None,
        is_synthetic=False,
        is_measured=True,
    )
    prov_db.add(orphan_q)
    prov_db.commit()
    prov_db.expire_all()

    q_res = client.get("/api/v1/queries/920002", headers=dba_headers)
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert q_data["captured_at"] is None
    assert q_data["provenance_state"] == ProvenanceState.HISTORICAL_OBSERVATION.value
    assert q_data["provenance_badge"] == ProvenanceBadgeLabel.HISTORICAL.value
    assert q_data["is_stale"] is True
    assert "missing" in (q_data["staleness_warning"] or "").lower()


def test_case_4_hypothetical_plan_estimates_cannot_appear_as_verified_speedups(
    prov_db: Session, dba_headers: dict[str, str]
):
    """Case 4: Hypothetical plan estimates are labeled ESTIMATED and cannot appear as measured or verified speedups."""
    client = TestClient(app)

    snap = WorkloadSnapshot(
        captured_at=datetime.now(timezone.utc),
        window_seconds=60.0,
        total_calls=100,
        total_exec_time_ms=25000.0,
        unique_queries=1,
        slow_queries=1,
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgresql://prod-db:5432/orders_db",
        collection_status="success",
        is_synthetic=False,
        is_measured=True,
    )
    prov_db.add(snap)
    prov_db.flush()

    q_stat = QueryStatistic(
        snapshot_id=snap.id,
        query_id=930003,
        database_name="orders_db",
        user_name="app_service",
        normalized_query="SELECT * FROM shipments WHERE tracking_code = $1",
        calls=100,
        total_exec_time_ms=25000.0,
        mean_exec_time_ms=250.0,
        min_exec_time_ms=100.0,
        max_exec_time_ms=500.0,
        rows=100,
        shared_blks_hit=200,
        shared_blks_read=1500,
        shared_blks_dirtied=0,
        shared_blks_written=0,
        local_blks_hit=0,
        local_blks_read=0,
        temp_blks_read=0,
        temp_blks_written=0,
        blk_read_time_ms=120.0,
        blk_write_time_ms=0.0,
        query_frequency_per_minute=100.0,
        predicate_info={"table": "shipments", "columns": ["tracking_code"]},
        explain_plan=[{"Plan": {"Node Type": "Seq Scan", "Relation Name": "shipments", "Total Cost": 3125.0}}],
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgresql://prod-db:5432/orders_db",
        is_synthetic=False,
        is_measured=True,
    )
    prov_db.add(q_stat)
    prov_db.commit()

    # Calculate hypothetical optimizations
    calc_res = client.post("/api/v1/queries/calculate-optimizations?query_id=930003", headers=dba_headers)
    assert calc_res.status_code == 200
    calc_data = calc_res.json()
    assert calc_data["result_type"] == ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
    assert calc_data["is_measured"] is False

    # Inspect query detail optimization_summary
    detail_res = client.get("/api/v1/queries/930003", headers=dba_headers)
    assert detail_res.status_code == 200
    opt_sum = detail_res.json()["optimization_summary"]
    assert opt_sum is not None
    assert opt_sum["provenance_state"] == ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
    assert opt_sum["provenance_badge"] == ProvenanceBadgeLabel.ESTIMATED.value
    assert opt_sum["is_measured"] is False
    assert opt_sum["is_verified_speedup"] is False
    assert opt_sum["measured_latency_ms"] is None
    assert "not a measured" in opt_sum["estimate_vs_measured_explanation"].lower()

    # Inspect generated simulation record
    sims_res = client.get("/api/v1/simulations", headers=dba_headers)
    assert sims_res.status_code == 200
    sims = sims_res.json()
    assert len(sims) == 1
    sim = sims[0]
    assert sim["provenance_state"] == ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
    assert sim["provenance_badge"] == ProvenanceBadgeLabel.ESTIMATED.value
    assert sim["result_type"] == ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value
    assert sim["is_measured"] is False
    assert sim["is_verified_speedup"] is False
    assert "not a measured" in sim["estimate_vs_measured_explanation"].lower()


def test_case_5_stale_telemetry_triggers_appropriate_warning(prov_db: Session, dba_headers: dict[str, str]):
    """Case 5: Stale telemetry in PostgreSQL resolves to HISTORICAL_OBSERVATION / HISTORICAL and triggers staleness_warning."""
    client = TestClient(app)
    stale_captured_at = datetime.now(timezone.utc) - timedelta(hours=3)

    snap = WorkloadSnapshot(
        captured_at=stale_captured_at,
        window_seconds=60.0,
        total_calls=300,
        total_exec_time_ms=45000.0,
        unique_queries=1,
        slow_queries=1,
        # Stored in DB as LIVE_TELEMETRY when originally collected 3 hours ago
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgresql://prod-db:5432/orders_db",
        collection_status="success",
        is_synthetic=False,
        is_measured=True,
    )
    prov_db.add(snap)
    prov_db.flush()

    q_stat = QueryStatistic(
        snapshot_id=snap.id,
        query_id=940004,
        database_name="orders_db",
        user_name="app_service",
        normalized_query="SELECT * FROM audit_trail WHERE actor_id = $1",
        calls=300,
        total_exec_time_ms=45000.0,
        mean_exec_time_ms=150.0,
        min_exec_time_ms=80.0,
        max_exec_time_ms=350.0,
        rows=300,
        shared_blks_hit=900,
        shared_blks_read=300,
        shared_blks_dirtied=0,
        shared_blks_written=0,
        local_blks_hit=0,
        local_blks_read=0,
        temp_blks_read=0,
        temp_blks_written=0,
        blk_read_time_ms=25.0,
        blk_write_time_ms=0.0,
        query_frequency_per_minute=300.0,
        predicate_info=None,
        explain_plan=None,
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgresql://prod-db:5432/orders_db",
        captured_at=stale_captured_at,
        is_synthetic=False,
        is_measured=True,
    )
    prov_db.add(q_stat)
    prov_db.commit()

    # Workload summary must NOT label 3-hour-old telemetry as LIVE
    summary_res = client.get("/api/v1/workload/summary", headers=dba_headers)
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["provenance_state"] == ProvenanceState.HISTORICAL_OBSERVATION.value
    assert summary["provenance_badge"] == ProvenanceBadgeLabel.HISTORICAL.value
    assert summary["is_stale"] is True
    assert summary["staleness_seconds"] >= 10000
    assert summary["staleness_warning"] is not None
    assert "stale" in summary["staleness_warning"].lower()

    # Query detail must also resolve to HISTORICAL_OBSERVATION with staleness warning
    q_res = client.get("/api/v1/queries/940004", headers=dba_headers)
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert q_data["provenance_state"] == ProvenanceState.HISTORICAL_OBSERVATION.value
    assert q_data["provenance_badge"] == ProvenanceBadgeLabel.HISTORICAL.value
    assert q_data["is_stale"] is True
    assert q_data["staleness_warning"] is not None


def test_case_6_rerunning_demo_initialization_preserves_legitimate_data(
    prov_db: Session, dba_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
):
    """Case 6: Re-running demo initialization preserves legitimate observations, recommendations, simulations, and audit events."""
    # Insert legitimate live telemetry snapshot, query stat, recommendation, simulation, and audit events
    live_snap = WorkloadSnapshot(
        captured_at=datetime.now(timezone.utc),
        window_seconds=60.0,
        total_calls=777,
        total_exec_time_ms=88888.0,
        unique_queries=1,
        slow_queries=1,
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgresql://prod-db:5432/legitimate_db",
        collection_status="success",
        is_synthetic=False,
        is_measured=True,
    )
    prov_db.add(live_snap)
    prov_db.flush()

    live_query = QueryStatistic(
        snapshot_id=live_snap.id,
        query_id=777001,
        database_name="legitimate_db",
        user_name="prod_user",
        normalized_query="SELECT * FROM legitimate_ledger WHERE account_id = $1",
        calls=777,
        total_exec_time_ms=88888.0,
        mean_exec_time_ms=114.4,
        min_exec_time_ms=20.0,
        max_exec_time_ms=410.0,
        rows=777,
        shared_blks_hit=5000,
        shared_blks_read=800,
        shared_blks_dirtied=0,
        shared_blks_written=0,
        local_blks_hit=0,
        local_blks_read=0,
        temp_blks_read=0,
        temp_blks_written=0,
        blk_read_time_ms=64.0,
        blk_write_time_ms=0.0,
        query_frequency_per_minute=777.0,
        predicate_info={"table": "legitimate_ledger", "columns": ["account_id"]},
        explain_plan=None,
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgresql://prod-db:5432/legitimate_db",
        is_synthetic=False,
        is_measured=True,
    )
    prov_db.add(live_query)

    live_rec = OptimizationRecommendation(
        recommendation_key="legitimate_ledger_idx_account",
        type="index_where",
        target="legitimate_ledger",
        proposed_change="CREATE INDEX CONCURRENTLY idx_legitimate_ledger_account ON legitimate_ledger (account_id);",
        reason="Observed seq scan on legitimate_ledger in live telemetry",
        evidence={"query_id": 777001},
        expected_benefit="72% planner cost reduction",
        risk="low",
        confidence=0.94,
        affected_queries=[{"query_id": 777001}],
        requires_approval=True,
        status="approved",
        provenance_state=ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value,
        source_identifier="postgresql://prod-db:5432/legitimate_db",
        is_synthetic=False,
        is_measured=False,
        model_version="advisor-engine-v0.7.0",
    )
    prov_db.add(live_rec)
    prov_db.flush()

    live_sim = OptimizationSimulation(
        recommendation_id=live_rec.id,
        status="completed",
        baseline_cost=4200.0,
        proposed_cost=1150.0,
        improvement=72.6,
        affected_queries=[{"query_id": 777001}],
        plan_differences=[],
        estimated_storage_impact={"estimated_index_bytes": 102400},
        write_overhead_estimate={"insert_overhead_pct": 1.2},
        confidence=0.94,
        limitations=[],
        benchmark={"runs": 3, "is_measured": True},
        baseline_plans=[],
        proposed_plans=[],
        provenance_state=ProvenanceState.SANDBOX_BENCHMARK.value,
        source_identifier="postgresql://sandbox-db:5432/legitimate_db",
        simulation_method="hypopg_sandbox_benchmark",
        result_type=ProvenanceState.SANDBOX_BENCHMARK.value,
        is_synthetic=False,
        is_measured=True,
        model_version="sandbox-simulator-v0.7.0",
    )
    prov_db.add(live_sim)

    live_rec_audit = RecommendationAuditEvent(
        recommendation_id=live_rec.id,
        action="approved",
        previous_status="pending",
        new_status="approved",
        reason="Approved by production DBA",
        metadata_json='{"verified": true}',
    )
    prov_db.add(live_rec_audit)

    live_sec_audit = SecurityAuditEvent(
        event_category="APPROVAL",
        action="recommendation_approved",
        actor_id="1",
        actor_username="dba_prov",
        actor_role="DBA",
        target_entity="OptimizationRecommendation",
        target_id=str(live_rec.id),
        status="SUCCESS",
        details_json='{"target": "legitimate_ledger"}',
    )
    prov_db.add(live_sec_audit)
    prov_db.commit()

    # 1. Verify auto_seed_if_empty() does NOT run when legitimate data already exists
    auto_res = auto_seed_if_empty(prov_db)
    assert auto_res is False

    # 2. Run generate_comprehensive_workload twice in a row
    seed_1 = generate_comprehensive_workload(existing_session=prov_db)
    assert seed_1["provenance_state"] == ProvenanceState.SYNTHETIC_DEMO.value
    seed_2 = generate_comprehensive_workload(existing_session=prov_db)
    assert seed_2["provenance_state"] == ProvenanceState.SYNTHETIC_DEMO.value

    # 3. Verify all legitimate records are 100% intact
    assert prov_db.get(WorkloadSnapshot, live_snap.id) is not None
    assert prov_db.get(QueryStatistic, live_query.id) is not None
    assert prov_db.get(OptimizationRecommendation, live_rec.id) is not None
    assert prov_db.get(OptimizationSimulation, live_sim.id) is not None
    assert prov_db.get(RecommendationAuditEvent, live_rec_audit.id) is not None
    assert prov_db.get(SecurityAuditEvent, live_sec_audit.id) is not None

    # Verify synthetic snapshots were replaced rather than duplicated infinitely (7 timeline snapshots, not 14)
    syn_snaps = prov_db.scalars(
        select(WorkloadSnapshot).where(WorkloadSnapshot.is_synthetic.is_(True))
    ).all()
    assert len(syn_snaps) == 7

    # 4. Verify ENABLE_DEMO_SEED=false disables auto_seed_if_empty even on an empty database
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_demo_seed", False)
    # Delete all rows to simulate an empty DB with ENABLE_DEMO_SEED=false
    prov_db.query(QueryStatistic).delete()
    prov_db.query(WorkloadSnapshot).delete()
    prov_db.commit()

    disabled_res = auto_seed_if_empty(prov_db)
    assert disabled_res is False
    assert prov_db.query(WorkloadSnapshot).count() == 0
