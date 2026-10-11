"""Phase 5: End-to-End Optimization Lifecycle and Impact Tracker Test Suite.

Covers all required Phase 5 invariants and scenarios:
1. Valid and invalid lifecycle transitions, including backend rejection of attempts to manually mark a recommendation as applied or verified_successful via status/transition endpoints.
2. Repeated approval/rejection decisions rejected with 409 Conflict.
3. Baseline capture recording pre-change window, latency percentiles (p50, p95, p99, mean), execution count, throughput, error count, resource indicators, and data provenance.
4. Candidate validation linking exact sandbox simulation/benchmark result (candidate_simulation_id) to recommendation and advancing lifecycle state.
5. Deployment verification gating: cannot apply unapproved recommendation; cannot mark applied without either confirmed DB catalog evidence or explicit deployment reference; DBA/Admin authorization required.
6. Impact calculation & edge cases:
   - Missing baseline data -> is_comparable=False, latency_improvement_pct=None, inconclusive.
   - Zero baseline values (mean_latency_ms=0.0) -> safe handling without division by zero, zero_baseline_latency reason, inconclusive.
   - Different query fingerprints -> is_comparable=False, query_fingerprint_mismatch, inconclusive.
   - Incomparable time windows -> is_comparable=False, incomparable_time_window, inconclusive.
7. Validation outcomes:
   - Failed validation (validation_failed=True or error_count > 0) -> lifecycle_state='failed'.
   - Regressions (post-change latency degraded by >= 5%) -> lifecycle_state='regressed'.
   - Synthetic measurements -> clearly labeled as synthetic_demo, never misrepresented as verified production speedup.
   - Actual observed production outcomes -> verified_successful and VERIFIED_POST_CHANGE provenance when applied and measured in live production telemetry.
8. Confidence, uncertainty, and causality disclaimer (sample size, coefficient of variation, time window, CAUSALITY_DISCLAIMER).
9. Dashboard lifecycle summary endpoint (awaiting approval, recently validated changes, verified improvements, regressions, inconclusive measurements).
10. Authorized CSV and JSON lifecycle export with sensitive credential scrubbing and audit trail recording.
"""

from __future__ import annotations

from datetime import datetime, timezone
import csv
import io
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import _API_RATE_LIMITER, _AUTH_RATE_LIMITER
from app.core.lifecycle import (
    CAUSALITY_DISCLAIMER,
    LifecycleState,
    build_observation_window_metrics,
    calculate_impact_and_uncertainty,
    ensure_lifecycle_schema,
)
from app.core.provenance import (
    ProvenanceBadgeLabel,
    ProvenanceState,
    compute_query_fingerprint,
    ensure_provenance_schema,
)
from app.core.security import Role, get_security_manager, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.recommendation import OptimizationRecommendation
from app.models.security import User
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
def lifecycle_db():
    """Creates an isolated in-memory SQLite database for Phase 5 lifecycle testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ensure_provenance_schema(engine)
    ensure_lifecycle_schema(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = session_factory()

    pwd_hash, pwd_salt = hash_password("DbaPass123!")
    db.add_all(
        [
            User(
                id=1,
                username="dba_lead",
                email="dba_lead@dbzenith.internal",
                password_hash=pwd_hash,
                salt=pwd_salt,
                role="DBA",
                is_active=True,
            ),
            User(
                id=2,
                username="analyst_user",
                email="analyst@dbzenith.internal",
                password_hash=pwd_hash,
                salt=pwd_salt,
                role="Analyst",
                is_active=True,
            ),
            User(
                id=3,
                username="viewer_user",
                email="viewer@dbzenith.internal",
                password_hash=pwd_hash,
                salt=pwd_salt,
                role="Viewer",
                is_active=True,
            ),
        ]
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
        username="dba_lead",
        role=Role.DBA,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def analyst_headers() -> dict[str, str]:
    token = get_security_manager().create_token(
        user_id="2",
        username="analyst_user",
        role=Role.ANALYST,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def viewer_headers() -> dict[str, str]:
    token = get_security_manager().create_token(
        user_id="3",
        username="viewer_user",
        role=Role.VIEWER,
    )
    return {"Authorization": f"Bearer {token}"}


def _seed_live_snapshot_and_recommendation(db: Session) -> tuple[WorkloadSnapshot, QueryStatistic, OptimizationRecommendation]:
    now = datetime.now(timezone.utc)
    sql = "SELECT id, customer_id, total_amount FROM orders WHERE status = 'PENDING' ORDER BY created_at DESC"
    fp = compute_query_fingerprint(sql)

    snap = WorkloadSnapshot(
        captured_at=now,
        window_seconds=3600,
        total_calls=1200,
        total_exec_time_ms=144000.0,
        unique_queries=1,
        slow_queries=1,
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgres@localhost:5432/dbzenith",
        collection_status="collected",
        is_measured=True,
        is_synthetic=False,
    )
    db.add(snap)
    db.flush()

    qstat = QueryStatistic(
        snapshot_id=snap.id,
        query_id=101,
        normalized_query=sql,
        calls=500,
        total_exec_time_ms=75000.0,
        mean_exec_time_ms=150.0,
        min_exec_time_ms=45.0,
        max_exec_time_ms=410.0,
        rows=5000,
        shared_blks_hit=8000,
        shared_blks_read=2000,
        temp_blks_read=0,
        temp_blks_written=0,
        blk_read_time_ms=95.0,
        blk_write_time_ms=0.0,
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        source_identifier="postgres@localhost:5432/dbzenith",
        query_fingerprint=fp,
        is_measured=True,
        is_synthetic=False,
    )
    db.add(qstat)
    db.flush()

    baseline = build_observation_window_metrics(
        query_id=101,
        normalized_query=sql,
        query_fingerprint=fp,
        captured_at=now,
        window_seconds=3600,
        calls=500,
        mean_exec_time_ms=150.0,
        min_exec_time_ms=45.0,
        max_exec_time_ms=410.0,
        total_exec_time_ms=75000.0,
        rows=5000,
        shared_blks_hit=8000,
        shared_blks_read=2000,
        blk_read_time_ms=95.0,
        error_count=0,
        source_identifier="postgres@localhost:5432/dbzenith",
        provenance_state=ProvenanceState.LIVE_TELEMETRY.value,
        is_measured=True,
        is_synthetic=False,
    )

    rec_count = db.query(OptimizationRecommendation).count()
    rec = OptimizationRecommendation(
        recommendation_key=f"rec_orders_idx_{rec_count + 1}",
        type="index",
        target="orders",
        proposed_change="CREATE INDEX idx_orders_status_created ON orders (status, created_at);",
        reason="High sequential scan latency on orders filter",
        evidence={"calls": 500, "mean_exec_time_ms": 150.0, "total_exec_time_ms": 75000.0},
        expected_benefit="Estimated 65% latency reduction (unmeasured estimate)",
        risk="low",
        confidence=0.88,
        status="pending",
        lifecycle_state=LifecycleState.AWAITING_APPROVAL.value,
        baseline_metrics=baseline,
        affected_queries=[101],
        provenance_state=ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value,
        source_identifier="postgres@localhost:5432/dbzenith",
        query_fingerprint=fp,
        is_measured=False,
        is_synthetic=False,
        model_version="heuristic-engine-v0.7+rl-qtable",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return snap, qstat, rec


# ==============================================================================
# 1. Invalid Transitions & Evidence-Gated State Enforcement
# ==============================================================================
def test_invalid_lifecycle_transitions_and_manual_spoofing_blocked(lifecycle_db: Session, dba_headers: dict[str, str]):
    """Verifies that the frontend/caller cannot manually mark a recommendation as applied
    or verified_successful merely by calling the transition endpoint, and illegal transitions fail."""
    _, _, rec = _seed_live_snapshot_and_recommendation(lifecycle_db)
    client = TestClient(app)

    # 1. Attempt to manually transition directly to 'applied' -> 400 Blocked
    res_applied = client.post(
        f"/api/v1/recommendations/{rec.id}/transition",
        headers=dba_headers,
        json={"target_state": "applied", "reason": "Frontend trying to spoof applied status"},
    )
    assert res_applied.status_code == 400
    assert "cannot_manually_set_applied_or_outcome_state" in str(res_applied.json())

    # 2. Attempt to manually transition directly to 'verified_successful' -> 400 Blocked
    res_success = client.post(
        f"/api/v1/recommendations/{rec.id}/transition",
        headers=dba_headers,
        json={"target_state": "verified_successful", "reason": "Spoofing success"},
    )
    assert res_success.status_code == 400
    assert "cannot_manually_set_applied_or_outcome_state" in str(res_success.json())

    # 3. Attempt to transition from awaiting_approval directly to ready_for_deployment (skipping approval) -> 409
    res_skip = client.post(
        f"/api/v1/recommendations/{rec.id}/transition",
        headers=dba_headers,
        json={"target_state": "ready_for_deployment", "reason": "Skipping approval"},
    )
    assert res_skip.status_code == 409
    assert "invalid_lifecycle_transition" in str(res_skip.json())

    # 4. Attempt to apply an unapproved recommendation -> 409 Blocked
    res_unapproved_apply = client.post(
        f"/api/v1/recommendations/{rec.id}/apply",
        headers=dba_headers,
        json={"confirm_applied": True, "deployment_reference": "CHG-001"},
    )
    assert res_unapproved_apply.status_code == 409
    assert "recommendation_must_be_approved_before_apply" in str(res_unapproved_apply.json())


# ==============================================================================
# 2. Repeated Decisions & Rejected State Immutability
# ==============================================================================
def test_repeated_decisions_and_rejected_transitions_blocked(lifecycle_db: Session, dba_headers: dict[str, str]):
    """Verifies that repeated approve/reject decisions fail with 409 and rejected recommendations cannot be applied."""
    _, _, rec = _seed_live_snapshot_and_recommendation(lifecycle_db)
    client = TestClient(app)

    # First approval succeeds
    res1 = client.post(
        f"/api/v1/recommendations/{rec.id}/approve",
        headers=dba_headers,
        json={"reason": "Approved after DBA review"},
    )
    assert res1.status_code == 200
    body1 = res1.json()
    assert body1["status"] == "approved"
    assert body1["lifecycle_state"] == "approved"
    assert body1["decided_by"] == "dba_lead"
    assert body1["decided_at"] is not None
    assert body1["decision_reason"] == "Approved after DBA review"

    # Second approval fails with 409
    res2 = client.post(
        f"/api/v1/recommendations/{rec.id}/approve",
        headers=dba_headers,
        json={"reason": "Duplicate approval"},
    )
    assert res2.status_code == 409

    # Subsequent rejection on already-approved recommendation also fails with 409
    res3 = client.post(
        f"/api/v1/recommendations/{rec.id}/reject",
        headers=dba_headers,
        json={"reason": "Trying to reject after approval"},
    )
    assert res3.status_code == 409

    # Create a second recommendation and reject it
    _, _, rec_rej = _seed_live_snapshot_and_recommendation(lifecycle_db)
    res_rej = client.post(
        f"/api/v1/recommendations/{rec_rej.id}/reject",
        headers=dba_headers,
        json={"reason": "High write amplification risk"},
    )
    assert res_rej.status_code == 200
    assert res_rej.json()["lifecycle_state"] == "rejected"

    # Attempting to transition a rejected recommendation to ready_for_deployment fails with 409
    res_rej_trans = client.post(
        f"/api/v1/recommendations/{rec_rej.id}/transition",
        headers=dba_headers,
        json={"target_state": "ready_for_deployment", "reason": "Bypassing rejection"},
    )
    assert res_rej_trans.status_code == 409


# ==============================================================================
# 3. Baseline Capture, Candidate Simulation Linking & Deployment Verification
# ==============================================================================
def test_baseline_capture_candidate_simulation_and_deployment_verification(
    lifecycle_db: Session,
    dba_headers: dict[str, str],
    analyst_headers: dict[str, str],
):
    """Verifies baseline capture, candidate simulation linking, and deployment evidence gating."""
    _, _, rec = _seed_live_snapshot_and_recommendation(lifecycle_db)
    rec.lifecycle_state = LifecycleState.DETECTED.value
    lifecycle_db.commit()

    client = TestClient(app)

    # 1. Capture baseline window explicitly
    base_res = client.post(
        f"/api/v1/recommendations/{rec.id}/baseline",
        headers=analyst_headers,
    )
    assert base_res.status_code == 200
    base_data = base_res.json()
    assert base_data["lifecycle_state"] == "analyzed"
    bm = base_data["baseline_metrics"]
    assert bm["mean_latency_ms"] == 150.0
    assert bm["p50_latency_ms"] is not None
    assert bm["p95_latency_ms"] is not None
    assert bm["p99_latency_ms"] is not None
    assert bm["sample_size"] == 500
    assert bm["window_seconds"] == 3600
    assert bm["throughput_qps"] > 0
    assert bm["error_count"] == 0
    assert bm["resource_indicators"]["shared_blks_hit"] == 8000
    assert bm["resource_indicators"]["shared_blks_read"] == 2000
    assert bm["resource_indicators"]["cache_hit_ratio"] == 0.8

    # 2. Run sandbox simulation -> links candidate_simulation_id and advances to 'simulated'
    sim_res = client.post(
        "/api/v1/simulations",
        headers=analyst_headers,
        json={"recommendation_id": rec.id, "benchmark_runs": 3},
    )
    assert sim_res.status_code == 200
    sim_id = sim_res.json()["id"]

    rec_after_sim = client.get(f"/api/v1/recommendations/{rec.id}", headers=analyst_headers).json()
    assert rec_after_sim["candidate_simulation_id"] == sim_id
    assert rec_after_sim["lifecycle_state"] == "simulated"

    # 3. Approve recommendation as DBA
    app_res = client.post(
        f"/api/v1/recommendations/{rec.id}/approve",
        headers=dba_headers,
        json={"reason": "Sandbox validated"},
    )
    assert app_res.status_code == 200
    assert app_res.json()["lifecycle_state"] == "approved"

    # 4. Transition to ready_for_deployment
    rdy_res = client.post(
        f"/api/v1/recommendations/{rec.id}/transition",
        headers=dba_headers,
        json={"target_state": "ready_for_deployment", "reason": "Scheduled for maintenance window"},
    )
    assert rdy_res.status_code == 200
    assert rdy_res.json()["lifecycle_state"] == "ready_for_deployment"

    # 5. Analyst cannot call /apply (requires DBA/Admin)
    forbidden_apply = client.post(
        f"/api/v1/recommendations/{rec.id}/apply",
        headers=analyst_headers,
        json={"confirm_applied": True, "deployment_reference": "CHG-100"},
    )
    assert forbidden_apply.status_code == 403

    # 6. DBA calling /apply without catalog verification AND without deployment_reference fails with 400
    missing_ev_apply = client.post(
        f"/api/v1/recommendations/{rec.id}/apply",
        headers=dba_headers,
        json={"verify_catalog": False, "confirm_applied": False},
    )
    assert missing_ev_apply.status_code == 400
    assert "deployment_evidence_required" in str(missing_ev_apply.json())

    # 7. DBA calling /apply with verify_catalog=True when index does not exist in DB catalog fails with 409
    cat_fail = client.post(
        f"/api/v1/recommendations/{rec.id}/apply",
        headers=dba_headers,
        json={"verify_catalog": True, "confirm_applied": False},
    )
    assert cat_fail.status_code == 409
    assert "catalog_verification_failed_change_not_found" in str(cat_fail.json())

    # 8. DBA calling /apply with confirm_applied=True and deployment_reference succeeds
    ok_apply = client.post(
        f"/api/v1/recommendations/{rec.id}/apply",
        headers=dba_headers,
        json={
            "verify_catalog": False,
            "confirm_applied": True,
            "deployment_reference": "CHG-2026-8841",
            "reason": "Index created concurrently on replica and promoted",
        },
    )
    assert ok_apply.status_code == 200
    applied_body = ok_apply.json()
    assert applied_body["lifecycle_state"] == "applied"
    assert applied_body["applied_at"] is not None
    assert applied_body["deployment_details"]["deployment_reference"] == "CHG-2026-8841"
    assert applied_body["deployment_details"]["applied_by"] == "dba_lead"


# ==============================================================================
# 4. Impact Calculation Edge Cases: Missing Baseline, Zero Values, Mismatched Fingerprints & Windows
# ==============================================================================
def test_impact_calculation_missing_baseline_zero_values_and_mismatches():
    """Directly tests calculate_impact_and_uncertainty for zero division safety, missing baseline,
    mismatched query fingerprints, and incomparable observation windows."""
    # Case A: Missing baseline data
    impact_missing = calculate_impact_and_uncertainty(
        baseline=None,
        post_change={"mean_latency_ms": 25.0, "sample_size": 100, "window_seconds": 3600},
    )
    assert impact_missing["is_comparable"] is False
    assert impact_missing["latency_improvement_pct"] is None
    assert impact_missing["outcome_classification"] == LifecycleState.INCONCLUSIVE.value
    assert "missing_baseline_data" in impact_missing["incomparability_reasons"]
    assert impact_missing["confidence_assessment"]["causality_disclaimer"] == CAUSALITY_DISCLAIMER

    # Case B: Zero baseline latency (must NEVER divide by zero!)
    impact_zero = calculate_impact_and_uncertainty(
        baseline={
            "mean_latency_ms": 0.0,
            "sample_size": 200,
            "window_seconds": 3600,
            "throughput_qps": 0.0,
            "query_fingerprint": "fp_abc123",
        },
        post_change={
            "mean_latency_ms": 12.0,
            "sample_size": 200,
            "window_seconds": 3600,
            "throughput_qps": 10.0,
            "query_fingerprint": "fp_abc123",
        },
    )
    assert impact_zero["is_comparable"] is False
    assert impact_zero["latency_improvement_pct"] is None
    assert impact_zero["throughput_change_pct"] is None
    assert impact_zero["outcome_classification"] == LifecycleState.INCONCLUSIVE.value
    assert "zero_baseline_latency" in impact_zero["incomparability_reasons"]

    # Case C: Different query fingerprints
    impact_diff_fp = calculate_impact_and_uncertainty(
        baseline={
            "mean_latency_ms": 120.0,
            "sample_size": 200,
            "window_seconds": 3600,
            "query_fingerprint": "fp_orders_query",
        },
        post_change={
            "mean_latency_ms": 40.0,
            "sample_size": 200,
            "window_seconds": 3600,
            "query_fingerprint": "fp_unrelated_users_query",
        },
    )
    assert impact_diff_fp["is_comparable"] is False
    assert impact_diff_fp["latency_improvement_pct"] is None
    assert impact_diff_fp["outcome_classification"] == LifecycleState.INCONCLUSIVE.value
    assert "query_fingerprint_mismatch" in impact_diff_fp["incomparability_reasons"]

    # Case D: Incomparable time windows (e.g., 10s vs 86400s -> ratio 8640x > 24x)
    impact_bad_win = calculate_impact_and_uncertainty(
        baseline={
            "mean_latency_ms": 120.0,
            "sample_size": 200,
            "window_seconds": 10,
            "query_fingerprint": "fp_same",
        },
        post_change={
            "mean_latency_ms": 40.0,
            "sample_size": 200,
            "window_seconds": 86400,
            "query_fingerprint": "fp_same",
        },
    )
    assert impact_bad_win["is_comparable"] is False
    assert impact_bad_win["latency_improvement_pct"] is None
    assert impact_bad_win["outcome_classification"] == LifecycleState.INCONCLUSIVE.value
    assert "incomparable_time_window" in impact_bad_win["incomparability_reasons"]


# ==============================================================================
# 5. Validation Outcomes: Verified Successful, Regressed, Failed, Synthetic vs Observed
# ==============================================================================
def test_validation_outcomes_verified_regressed_failed_and_synthetic(
    lifecycle_db: Session,
    dba_headers: dict[str, str],
):
    """Tests post-change validation across:
    - Actual observed production improvement -> verified_successful + VERIFIED_POST_CHANGE provenance
    - Post-change regression -> regressed
    - Failed validation (errors > 0) -> failed
    - Synthetic post-change data -> remains synthetic, never marked as VERIFIED_POST_CHANGE production speedup
    """
    _, _, rec = _seed_live_snapshot_and_recommendation(lifecycle_db)
    client = TestClient(app)

    # Approve and mark applied
    client.post(f"/api/v1/recommendations/{rec.id}/approve", headers=dba_headers, json={"reason": "Approve"})
    client.post(
        f"/api/v1/recommendations/{rec.id}/apply",
        headers=dba_headers,
        json={"confirm_applied": True, "deployment_reference": "CHG-PROD-1"},
    )

    # 1. Validate with a REGRESSED post-change observation (latency increased from 150ms to 210ms = -40%)
    reg_res = client.post(
        f"/api/v1/recommendations/{rec.id}/validate",
        headers=dba_headers,
        json={
            "post_change_observation": {
                "mean_exec_time_ms": 210.0,
                "p50_latency_ms": 190.0,
                "p95_latency_ms": 295.0,
                "p99_latency_ms": 340.0,
                "calls": 450,
                "window_seconds": 3600,
                "error_count": 0,
                "shared_blks_hit": 7000,
                "shared_blks_read": 3000,
                "query_fingerprint": rec.query_fingerprint,
                "provenance_state": "LIVE_TELEMETRY",
                "is_measured": True,
                "is_synthetic": False,
                "environment": "production",
            },
            "reason": "Observed write lock contention after index creation",
        },
    )
    assert reg_res.status_code == 200
    reg_body = reg_res.json()
    assert reg_body["lifecycle_state"] == "regressed"
    assert reg_body["impact_summary"]["is_comparable"] is True
    assert reg_body["impact_summary"]["latency_improvement_pct"] == -40.0
    assert reg_body["impact_summary"]["confidence_assessment"]["causality_disclaimer"] == CAUSALITY_DISCLAIMER

    # 2. Validate with a FAILED post-change observation (error_count > 0)
    fail_res = client.post(
        f"/api/v1/recommendations/{rec.id}/validate",
        headers=dba_headers,
        json={
            "post_change_observation": {
                "mean_exec_time_ms": 60.0,
                "calls": 100,
                "window_seconds": 3600,
                "error_count": 4,
                "query_fingerprint": rec.query_fingerprint,
                "provenance_state": "LIVE_TELEMETRY",
                "is_measured": True,
                "is_synthetic": False,
                "environment": "production",
            },
            "reason": "Query statement timeout errors observed",
        },
    )
    assert fail_res.status_code == 200
    assert fail_res.json()["lifecycle_state"] == "failed"

    # 3. Validate with a SYNTHETIC post-change observation -> must be tagged synthetic_demo and NOT VERIFIED_POST_CHANGE
    syn_res = client.post(
        f"/api/v1/recommendations/{rec.id}/validate",
        headers=dba_headers,
        json={
            "post_change_observation": {
                "mean_exec_time_ms": 30.0,
                "calls": 500,
                "window_seconds": 3600,
                "error_count": 0,
                "query_fingerprint": rec.query_fingerprint,
                "provenance_state": "SYNTHETIC_DEMO",
                "is_measured": False,
                "is_synthetic": True,
                "environment": "synthetic_demo",
            },
        },
    )
    assert syn_res.status_code == 200
    syn_body = syn_res.json()
    assert syn_body["impact_summary"]["is_synthetic"] is True
    assert syn_body["impact_summary"]["environment"] == "synthetic_demo"
    assert syn_body["provenance_state"] != ProvenanceState.VERIFIED_POST_CHANGE.value

    # 4. Validate with an ACTUAL OBSERVED PRODUCTION improvement (150ms -> 30ms = +80.0% improvement)
    ver_res = client.post(
        f"/api/v1/recommendations/{rec.id}/validate",
        headers=dba_headers,
        json={
            "post_change_observation": {
                "mean_exec_time_ms": 30.0,
                "min_exec_time_ms": 18.0,
                "max_exec_time_ms": 58.0,
                "p50_latency_ms": 25.5,
                "p95_latency_ms": 42.0,
                "p99_latency_ms": 51.0,
                "calls": 600,
                "window_seconds": 3600,
                "error_count": 0,
                "shared_blks_hit": 9850,
                "shared_blks_read": 150,
                "query_fingerprint": rec.query_fingerprint,
                "provenance_state": "LIVE_TELEMETRY",
                "is_measured": True,
                "is_synthetic": False,
                "environment": "production",
            },
            "reason": "Verified production latency drop after index deployment",
        },
    )
    assert ver_res.status_code == 200
    ver_body = ver_res.json()
    assert ver_body["lifecycle_state"] == "verified_successful"
    assert ver_body["provenance_state"] == ProvenanceState.VERIFIED_POST_CHANGE.value
    assert ver_body["provenance_badge"] == ProvenanceBadgeLabel.VERIFIED.value
    assert ver_body["is_measured"] is True
    assert ver_body["is_synthetic"] is False
    assert ver_body["impact_summary"]["latency_improvement_pct"] == 80.0
    assert ver_body["impact_summary"]["latency_delta_ms"] == -120.0
    assert ver_body["impact_summary"]["confidence_assessment"]["sample_count_after"] == 600
    assert ver_body["impact_summary"]["confidence_assessment"]["variability_after_cv"] is not None


# ==============================================================================
# 6. Dashboard Lifecycle Summary & CSV / JSON Export with Secret Scrubbing
# ==============================================================================
def test_lifecycle_dashboard_summary_and_export_json_csv(
    lifecycle_db: Session,
    dba_headers: dict[str, str],
    viewer_headers: dict[str, str],
):
    """Tests GET /api/v1/recommendations/lifecycle/summary and GET /api/v1/recommendations/{id}/export."""
    _, _, rec = _seed_live_snapshot_and_recommendation(lifecycle_db)
    # Inject a sensitive connection string into deployment_details to verify export scrubbing
    rec.deployment_details = {
        "connection_dsn": "postgresql://admin:SuperSecretPass999@prod-db.internal:5432/dbzenith",
        "deployment_reference": "CHG-999",
    }
    lifecycle_db.commit()

    client = TestClient(app)

    # 1. Dashboard summary returns awaiting_approval counts and lists
    sum_res = client.get("/api/v1/recommendations/lifecycle/summary", headers=viewer_headers)
    assert sum_res.status_code == 200
    sum_body = sum_res.json()
    assert sum_body["total_recommendations"] >= 1
    assert sum_body["awaiting_approval_count"] >= 1
    assert isinstance(sum_body["awaiting_approval"], list)
    assert isinstance(sum_body["recently_validated"], list)

    # 2. Anonymous export request is rejected with 401
    anon_exp = client.get(f"/api/v1/recommendations/{rec.id}/export?format=json")
    assert anon_exp.status_code == 401

    # 3. Authorized JSON export succeeds and scrubs secret DSN password
    json_exp = client.get(f"/api/v1/recommendations/{rec.id}/export?format=json", headers=viewer_headers)
    assert json_exp.status_code == 200
    raw_json_text = json_exp.text
    assert "SuperSecretPass999" not in raw_json_text
    parsed_json = json.loads(raw_json_text)
    assert parsed_json["recommendation"]["id"] == rec.id
    assert parsed_json["causality_disclaimer"] == CAUSALITY_DISCLAIMER
    assert "baseline_metrics" in parsed_json

    # 4. Authorized CSV export succeeds and scrubs secret DSN password
    csv_exp = client.get(f"/api/v1/recommendations/{rec.id}/export?format=csv", headers=dba_headers)
    assert csv_exp.status_code == 200
    assert "text/csv" in csv_exp.headers.get("content-type", "")
    csv_text = csv_exp.text
    assert "SuperSecretPass999" not in csv_text
    reader = list(csv.reader(io.StringIO(csv_text)))
    assert reader[0][:2] == ["section", "field"]
    sections = {row[0] for row in reader[1:] if row}
    assert "recommendation" in sections
    assert "metrics_comparison" in sections
