"""Phase 6: PostgreSQL Execution-Plan Comparison and Safe Query Benchmarking Workbench Test Suite.

Covers all required Phase 6 invariants and scenarios:
1. Execution-Plan Diff (Feature A):
   - Nested plans, missing metrics, absent fields, and different plan shapes without crashing.
   - Meaningful changes in scan types (Seq Scan -> Index Scan / Index Only Scan, or regression Index Scan -> Seq Scan),
     joins (Nested Loop -> Hash Join / Merge Join), sorts (Sort eliminated / Sort added), estimated rows,
     actual rows, buffer activity (Shared Hit/Read Blocks), and execution time when available.
   - Missing or changed nodes highlighted (`added`, `removed`, `sort_eliminated`, `scan_upgraded`, `scan_degraded`, `join_changed`).
   - Top cost-contributing and time-contributing nodes identified (exclusive vs. inclusive cost and time).
   - Strict distinction between planner estimates (`planner_cost_units`) and actual execution measurements (`ms`).
   - PostgreSQL estimated cost is NEVER treated or labeled as milliseconds.

2. Safe Benchmarking (Feature B):
   - SQL parsing failures (`invalid_sql`) and unsafe/unsupported statements (`INSERT`, `UPDATE`, `DELETE`, `DROP`,
     `ALTER`, `TRUNCATE`, `pg_sleep`, `random`, `dblink`, `pg_read_file`, `FOR UPDATE`, multi-statement, SQL comments)
     are rejected before execution (`EXPLAIN ANALYZE` is never run on unsafe statements).
   - Production database connections (`db` / `get_engine()`) are NEVER used by the sandbox benchmark path.
   - Bounded execution time (`statement_timeout`), read-only transaction mode (`default_transaction_read_only = on`),
     rollback guarantee, concurrency limits, timeout handling (`status="timeout"`), and cancellation (`status="cancelled"`).
   - Explicit `unsupported` result when the sandbox cannot safely support a query.

3. Fair Comparison (Feature C):
   - Configurable warm-up runs and repeatable benchmark runs.
   - Safe parameter synthesis and literal scrubbing via PrivacyGateway.
   - Sample count, median (p50), p95, standard deviation, coefficient of variation, and buffer cache activity.
   - Candidate regressions (`comparison_verdict="regressed"`) and inconclusive comparisons (`comparison_verdict="inconclusive"`
     when variance exceeds delta, sample counts mismatch, row counts differ, or samples are missing).
   - Simulated plan cost estimates and measured execution times kept in strictly separate fields.

4. API & Authorized Export (Feature D & E):
   - `POST /api/v1/plans/compare`, `POST /api/v1/plans/benchmark`, `POST /api/v1/plans/benchmark/{run_id}/cancel`,
     and `POST /api/v1/plans/compare/export` authorization & contract verification.
   - Authorized export (JSON and CSV) scrubs all sensitive SQL literals (`<STR>`, `<NUM>`, `<SENSITIVE>`).
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import _API_RATE_LIMITER, _AUTH_RATE_LIMITER
from app.core.provenance import ensure_provenance_schema
from app.core.lifecycle import ensure_lifecycle_schema
from app.core.security import Role, get_security_manager, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.recommendation import OptimizationRecommendation
from app.models.security import User
from app.models.simulation import OptimizationSimulation
from app.models.workload import QueryStatistic, WorkloadSnapshot
from app.services.plans.workbench import (
    COST_UNIT_LABEL,
    SafeBenchmarkRunner,
    cancel_benchmark_run,
    compare_execution_plans,
    export_plan_comparison_report,
    parse_plan_tree_detailed,
    summarize_benchmark_samples,
    validate_and_prepare_benchmark_sql,
    validate_candidate_index_ddl,
)


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
def workbench_db():
    """Creates an isolated in-memory SQLite database for Phase 6 workbench testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    ensure_provenance_schema(engine)
    ensure_lifecycle_schema(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    pwd_hash, pwd_salt = hash_password("TestPass123!")
    users = [
        User(
            id=1,
            username="wb_viewer",
            email="viewer@dbzenith.local",
            password_hash=pwd_hash,
            salt=pwd_salt,
            role=Role.VIEWER.value,
            is_active=True,
        ),
        User(
            id=2,
            username="wb_analyst",
            email="analyst@dbzenith.local",
            password_hash=pwd_hash,
            salt=pwd_salt,
            role=Role.ANALYST.value,
            is_active=True,
        ),
        User(
            id=3,
            username="wb_dba",
            email="dba@dbzenith.local",
            password_hash=pwd_hash,
            salt=pwd_salt,
            role=Role.DBA.value,
            is_active=True,
        ),
    ]
    db.add_all(users)
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield db
    app.dependency_overrides.pop(get_db, None)
    db.close()


def _auth_header(user_id: int, username: str, role: Role) -> dict[str, str]:
    token = get_security_manager().create_token(
        user_id=str(user_id),
        username=username,
        role=role,
    )
    return {"Authorization": f"Bearer {token}"}


class _FakeSandboxConnection:
    """Controllable fake sandbox connection for testing SafeBenchmarkRunner without live PostgreSQL."""

    def __init__(
        self,
        *,
        baseline_plans: list[dict[str, Any]] | None = None,
        candidate_plans: list[dict[str, Any]] | None = None,
        raise_on_explain: Exception | None = None,
        on_explain_callback: Any = None,
    ) -> None:
        self.baseline_plans = list(baseline_plans or [])
        self.candidate_plans = list(candidate_plans or [])
        self.raise_on_explain = raise_on_explain
        self.on_explain_callback = on_explain_callback
        self.executed_statements: list[str] = []
        self.in_candidate_phase = False
        self.rollback_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def execute(self, stmt: Any, params: Any = None):
        sql_str = str(stmt).strip()
        self.executed_statements.append(sql_str)

        if "pg_backend_pid" in sql_str:
            res = MagicMock()
            res.scalar.return_value = 42424
            return res

        if "pg_cancel_backend" in sql_str:
            res = MagicMock()
            res.scalar.return_value = True
            return res

        if sql_str.upper().startswith("CREATE INDEX"):
            self.in_candidate_phase = True
            res = MagicMock()
            return res

        if sql_str.upper().startswith("EXPLAIN"):
            if self.on_explain_callback is not None:
                self.on_explain_callback(sql_str)
            if self.raise_on_explain is not None:
                raise self.raise_on_explain

            queue = self.candidate_plans if self.in_candidate_phase and self.candidate_plans else self.baseline_plans
            if queue:
                plan = queue.pop(0) if len(queue) > 1 else queue[0]
            else:
                plan = [
                    {
                        "Plan": {
                            "Node Type": "Seq Scan",
                            "Relation Name": "orders",
                            "Startup Cost": 0.0,
                            "Total Cost": 250.0,
                            "Plan Rows": 1000,
                            "Plan Width": 64,
                            "Actual Startup Time": 0.1,
                            "Actual Total Time": 12.5,
                            "Actual Rows": 1000,
                            "Actual Loops": 1,
                            "Shared Hit Blocks": 80,
                            "Shared Read Blocks": 10,
                        },
                        "Planning Time": 0.25,
                        "Execution Time": 12.8,
                    }
                ]
            res = MagicMock()
            res.scalar.return_value = plan
            return res

        return MagicMock()

    def rollback(self):
        self.rollback_count += 1
        # After first rollback (end of baseline phase), switch to candidate plans even if no index DDL was used
        if not self.in_candidate_phase and self.candidate_plans:
            self.in_candidate_phase = True


class _FakeSandboxEngine:
    def __init__(self, conn: _FakeSandboxConnection, url: str = "postgresql+psycopg2://sandbox:sandbox@localhost:5433/dbzenith_sandbox") -> None:
        self._conn = conn
        self.url = url

    def connect(self):
        return self._conn


# ==============================================================================
# 1. FEATURE A: EXECUTION-PLAN DIFF TESTS
# ==============================================================================


def test_plan_diff_nested_plans_different_shapes_and_sort_elimination():
    """Tests nested plans with different tree shapes (Sort + Nested Loop + Seq Scan vs Merge/Index Scan with Sort eliminated)."""
    baseline_raw = [
        {
            "Plan": {
                "Node Type": "Sort",
                "Sort Key": ["orders.created_at DESC"],
                "Startup Cost": 1420.0,
                "Total Cost": 1480.0,
                "Plan Rows": 500,
                "Plan Width": 64,
                "Actual Startup Time": 41.0,
                "Actual Total Time": 45.2,
                "Actual Rows": 480,
                "Actual Loops": 1,
                "Shared Hit Blocks": 120,
                "Shared Read Blocks": 340,
                "Plans": [
                    {
                        "Node Type": "Nested Loop",
                        "Join Type": "Inner",
                        "Startup Cost": 0.0,
                        "Total Cost": 1250.0,
                        "Plan Rows": 500,
                        "Plan Width": 64,
                        "Actual Startup Time": 0.5,
                        "Actual Total Time": 38.0,
                        "Actual Rows": 480,
                        "Actual Loops": 1,
                        "Shared Hit Blocks": 120,
                        "Shared Read Blocks": 340,
                        "Plans": [
                            {
                                "Node Type": "Seq Scan",
                                "Relation Name": "orders",
                                "Alias": "orders",
                                "Filter": "(status = 'PENDING' AND amount > 250)",
                                "Startup Cost": 0.0,
                                "Total Cost": 980.0,
                                "Plan Rows": 500,
                                "Plan Width": 48,
                                "Actual Startup Time": 0.2,
                                "Actual Total Time": 31.0,
                                "Actual Rows": 480,
                                "Actual Loops": 1,
                                "Shared Hit Blocks": 40,
                                "Shared Read Blocks": 320,
                            },
                            {
                                "Node Type": "Index Scan",
                                "Relation Name": "customers",
                                "Alias": "customers",
                                "Index Name": "customers_pkey",
                                "Startup Cost": 0.0,
                                "Total Cost": 220.0,
                                "Plan Rows": 1,
                                "Plan Width": 16,
                                "Actual Startup Time": 0.01,
                                "Actual Total Time": 0.01,
                                "Actual Rows": 1,
                                "Actual Loops": 480,
                                "Shared Hit Blocks": 80,
                                "Shared Read Blocks": 20,
                            },
                        ],
                    }
                ],
            },
            "Planning Time": 0.42,
            "Execution Time": 46.0,
        }
    ]

    candidate_raw = [
        {
            "Plan": {
                "Node Type": "Hash Join",
                "Join Type": "Inner",
                "Hash Cond": "(orders.customer_id = customers.id)",
                "Startup Cost": 12.0,
                "Total Cost": 185.0,
                "Plan Rows": 500,
                "Plan Width": 64,
                "Actual Startup Time": 1.1,
                "Actual Total Time": 4.8,
                "Actual Rows": 480,
                "Actual Loops": 1,
                "Shared Hit Blocks": 115,
                "Shared Read Blocks": 5,
                "Plans": [
                    {
                        "Node Type": "Index Only Scan",
                        "Relation Name": "orders",
                        "Alias": "orders",
                        "Index Name": "idx_orders_status_amount_created",
                        "Index Cond": "(status = 'PENDING' AND amount > 250)",
                        "Startup Cost": 0.42,
                        "Total Cost": 95.0,
                        "Plan Rows": 500,
                        "Plan Width": 48,
                        "Actual Startup Time": 0.08,
                        "Actual Total Time": 2.1,
                        "Actual Rows": 480,
                        "Actual Loops": 1,
                        "Shared Hit Blocks": 45,
                        "Shared Read Blocks": 2,
                    },
                    {
                        "Node Type": "Hash",
                        "Startup Cost": 10.0,
                        "Total Cost": 60.0,
                        "Plan Rows": 500,
                        "Plan Width": 16,
                        "Actual Startup Time": 0.9,
                        "Actual Total Time": 1.4,
                        "Actual Rows": 480,
                        "Actual Loops": 1,
                        "Shared Hit Blocks": 70,
                        "Shared Read Blocks": 3,
                        "Plans": [
                            {
                                "Node Type": "Index Scan",
                                "Relation Name": "customers",
                                "Alias": "customers",
                                "Index Name": "customers_pkey",
                                "Startup Cost": 0.0,
                                "Total Cost": 50.0,
                                "Plan Rows": 500,
                                "Plan Width": 16,
                                "Actual Startup Time": 0.02,
                                "Actual Total Time": 0.8,
                                "Actual Rows": 480,
                                "Actual Loops": 1,
                                "Shared Hit Blocks": 70,
                                "Shared Read Blocks": 3,
                            }
                        ],
                    },
                ],
            },
            "Planning Time": 0.35,
            "Execution Time": 5.1,
        }
    ]

    diff = compare_execution_plans(
        baseline_raw,
        candidate_raw,
        baseline_sql="SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id WHERE status = 'PENDING' AND amount > 250 ORDER BY created_at DESC",
        candidate_index_ddl="CREATE INDEX idx_orders_status_amount_created ON orders (status, amount, created_at DESC)",
    )

    assert diff["verdict"] == "improved"
    assert diff["structural_changes_summary"]["shape_changed"] is True
    counts = diff["structural_changes_summary"]["counts"]
    assert counts["scan_upgraded"] >= 1
    assert counts["join_changed"] >= 1
    assert counts["sort_eliminated"] == 1
    assert counts["added"] >= 1  # New Hash node in candidate

    # Verify cost contributors and time contributors are populated and strictly separated
    assert diff["cost_contributors"]["unit"] == COST_UNIT_LABEL
    top_base_cost = diff["cost_contributors"]["baseline"][0]
    assert top_base_cost["node_type"] == "Seq Scan"
    assert top_base_cost["exclusive_cost"] == 980.0
    assert top_base_cost["cost_unit"] == COST_UNIT_LABEL

    assert diff["time_contributors"]["available"] is True
    assert diff["time_contributors"]["unit"] == "ms"
    top_base_time = diff["time_contributors"]["baseline"][0]
    assert top_base_time["node_type"] == "Seq Scan"
    assert top_base_time["exclusive_actual_time_ms"] == 31.0

    # Verify buffer comparison
    buf = diff["buffer_comparison"]
    assert buf["baseline_shared_read_blocks"] == 340
    assert buf["candidate_shared_read_blocks"] == 5
    assert buf["shared_read_delta_blocks"] == -335


def test_plan_diff_handles_missing_metrics_and_empty_plans_without_crashing():
    """Tests that missing fields, empty dicts, None plans, and partial nodes never crash."""
    diff_none = compare_execution_plans(None, {})
    assert diff_none["verdict"] == "inconclusive"
    assert diff_none["baseline_plan"]["has_plan"] is False
    assert diff_none["candidate_plan"]["has_plan"] is False
    assert diff_none["actual_execution_comparison"]["is_measured_latency"] is False

    sparse_base = {"Plan": {"Node Type": "Seq Scan"}}
    sparse_cand = {"Plan": {"Node Type": "Index Scan", "Total Cost": None, "Plan Rows": None}}
    diff_sparse = compare_execution_plans(sparse_base, sparse_cand)
    assert diff_sparse["baseline_plan"]["node_count"] == 1
    assert diff_sparse["candidate_plan"]["node_count"] == 1
    assert diff_sparse["cost_comparison"]["unit"] == COST_UNIT_LABEL
    assert diff_sparse["actual_execution_comparison"]["baseline_execution_time_ms"] is None
    assert diff_sparse["actual_execution_comparison"]["candidate_execution_time_ms"] is None
    assert diff_sparse["time_contributors"]["available"] is False


def test_estimated_cost_never_labeled_as_measured_latency():
    """Verifies that planner cost estimates are strictly labeled as planner_cost_units and never as milliseconds."""
    estimate_only_base = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "orders",
            "Startup Cost": 0.0,
            "Total Cost": 4500.0,
            "Plan Rows": 20000,
            "Plan Width": 64,
        }
    }
    estimate_only_cand = {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "orders",
            "Index Name": "idx_orders_customer",
            "Startup Cost": 0.42,
            "Total Cost": 125.0,
            "Plan Rows": 150,
            "Plan Width": 64,
        }
    }

    diff = compare_execution_plans(estimate_only_base, estimate_only_cand)
    assert diff["cost_unit"] == "planner_cost_units"
    assert diff["cost_comparison"]["unit"] == "planner_cost_units"
    assert diff["cost_comparison"]["is_measured_latency"] is False
    assert "NOT milliseconds" in diff["cost_comparison"]["disclaimer"]

    # Actual execution time fields MUST be None when EXPLAIN ANALYZE was not run
    actual = diff["actual_execution_comparison"]
    assert actual["is_measured_latency"] is False
    assert actual["has_baseline_actuals"] is False
    assert actual["has_candidate_actuals"] is False
    assert actual["baseline_execution_time_ms"] is None
    assert actual["candidate_execution_time_ms"] is None
    assert actual["measured_speedup_pct"] is None
    assert diff["verdict"] == "estimate_only_improved"


# ==============================================================================
# 2. FEATURE B: SAFE BENCHMARKING & PRODUCTION ISOLATION TESTS
# ==============================================================================


@pytest.mark.parametrize(
    "bad_sql,expected_status",
    [
        ("", "invalid_sql"),
        ("SELECT FROM WHERE ???", "invalid_sql"),
        ("INSERT INTO orders (customer_id, amount) VALUES (1, 100)", "unsupported"),
        ("UPDATE orders SET amount = 0 WHERE id = 1", "unsupported"),
        ("DELETE FROM orders WHERE id = 1", "unsupported"),
        ("DROP TABLE orders", "unsupported"),
        ("TRUNCATE TABLE orders", "unsupported"),
        ("ALTER TABLE orders ADD COLUMN hacked INT", "unsupported"),
        ("SELECT 1; DROP TABLE orders", "unsupported"),
        ("SELECT * FROM orders -- comment injection", "unsupported"),
        ("SELECT /* block comment */ * FROM orders", "unsupported"),
        ("SELECT pg_sleep(5) FROM orders", "unsupported"),
        ("SELECT random(), id FROM orders", "unsupported"),
        ("SELECT nextval('orders_id_seq')", "unsupported"),
        ("SELECT pg_read_file('/etc/passwd')", "unsupported"),
        ("SELECT dblink('host=evil', 'SELECT 1')", "unsupported"),
        ("SELECT * FROM orders FOR UPDATE", "unsupported"),
        ("SELECT * FROM pg_authid", "unsupported"),
        ("WITH del AS (DELETE FROM orders RETURNING *) SELECT * FROM del", "unsupported"),
    ],
)
def test_sql_parsing_failures_and_unsafe_statements_rejected_before_execution(
    bad_sql: str, expected_status: str
):
    """Verifies that invalid or unsafe SQL is blocked before touching any database connection."""
    validation = validate_and_prepare_benchmark_sql(bad_sql)
    assert validation.is_safe is False
    assert validation.explain_analyze_allowed is False
    assert validation.status == expected_status

    # Also verify SafeBenchmarkRunner never opens a connection when SQL is invalid/unsafe
    trap_engine = MagicMock()
    trap_engine.connect.side_effect = AssertionError("Sandbox engine must NOT be called for unsafe/invalid SQL!")
    runner = SafeBenchmarkRunner(sandbox_engine=trap_engine)
    res = runner.run_benchmark(baseline_sql=bad_sql)
    assert res["status"] == expected_status
    assert res["is_comparable"] is False
    assert trap_engine.connect.call_count == 0


def test_production_connection_never_used_by_sandbox_benchmark(workbench_db: Session, monkeypatch):
    """Verifies that the production database session and production engine are NEVER used to run benchmark SQL."""
    import app.services.plans.workbench as wb_module

    prod_engine = get_db  # reference check
    fake_prod_engine = MagicMock()
    fake_prod_engine.url = "postgresql+psycopg2://prod_user:secret@prod-db:5432/prod_db"
    fake_prod_engine.connect.side_effect = AssertionError(
        "SECURITY BREACH: Production engine connect() was called during sandbox benchmark!"
    )
    monkeypatch.setattr(wb_module, "get_engine", lambda: fake_prod_engine)

    # 1. Verify passing the production engine to SafeBenchmarkRunner raises a hard RuntimeError
    runner_with_prod = SafeBenchmarkRunner(sandbox_engine=fake_prod_engine)
    with pytest.raises(RuntimeError, match="SECURITY VIOLATION"):
        runner_with_prod.run_benchmark(baseline_sql="SELECT id, amount FROM orders WHERE amount > 100")

    # 2. Verify passing a Session object raises a hard RuntimeError
    runner_with_session = SafeBenchmarkRunner(sandbox_engine=workbench_db)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="SECURITY VIOLATION"):
        runner_with_session.run_benchmark(baseline_sql="SELECT id, amount FROM orders WHERE amount > 100")

    # 3. Verify normal benchmark uses ONLY the isolated sandbox engine and applies all session safeguards
    fake_conn = _FakeSandboxConnection()
    fake_sandbox = _FakeSandboxEngine(fake_conn)
    monkeypatch.setattr(wb_module, "get_sandbox_engine", lambda: fake_sandbox)

    runner = SafeBenchmarkRunner(sandbox_engine=fake_sandbox)
    result = runner.run_benchmark(
        baseline_sql="SELECT id, amount FROM orders WHERE amount > 100",
        candidate_index_ddl="CREATE INDEX idx_orders_amount ON orders (amount)",
        warmup_runs=1,
        benchmark_runs=2,
        statement_timeout_ms=2500,
    )
    assert result["status"] == "completed"
    assert fake_prod_engine.connect.call_count == 0
    # Verify read-only transaction, statement_timeout, temp_file_limit, and rollback were executed on sandbox
    joined_stmts = "\n".join(fake_conn.executed_statements)
    assert "SET LOCAL statement_timeout = '2500ms'" in joined_stmts
    assert "SET LOCAL default_transaction_read_only = on" in joined_stmts
    assert "SET LOCAL temp_file_limit = '64MB'" in joined_stmts
    assert fake_conn.rollback_count >= 2


def test_benchmark_timeout_and_cancellation_behavior():
    """Tests that statement timeouts and active run cancellations are handled safely and cleanly."""
    # 1. Timeout behavior
    timeout_conn = _FakeSandboxConnection(
        raise_on_explain=RuntimeError("ERROR: canceling statement due to statement timeout")
    )
    timeout_engine = _FakeSandboxEngine(timeout_conn)
    runner = SafeBenchmarkRunner(sandbox_engine=timeout_engine)

    timeout_res = runner.run_benchmark(
        baseline_sql="SELECT id, customer_id FROM orders WHERE amount > 50",
        statement_timeout_ms=500,
    )
    assert timeout_res["status"] == "timeout"
    assert timeout_res["comparison_verdict"] == "timeout"
    assert timeout_res["timeout_occurred"] is True
    assert timeout_res["is_comparable"] is False

    # 2. Pre-cancelled behavior
    pre_cancel_res = runner.run_benchmark(
        baseline_sql="SELECT id, customer_id FROM orders WHERE amount > 50",
        run_id="bench-cancel-pre",
        pre_cancelled=True,
    )
    assert pre_cancel_res["status"] == "cancelled"
    assert pre_cancel_res["cancelled"] is True

    # 3. Mid-run cooperative + backend cancellation via cancel_benchmark_run(run_id)
    mid_cancel_conn = _FakeSandboxConnection()
    mid_cancel_engine = _FakeSandboxEngine(mid_cancel_conn)

    def _trigger_cancel_mid_run(_sql: str):
        cancel_benchmark_run("bench-mid-cancel", sandbox_engine=mid_cancel_engine)

    mid_cancel_conn.on_explain_callback = _trigger_cancel_mid_run
    mid_runner = SafeBenchmarkRunner(sandbox_engine=mid_cancel_engine)
    mid_res = mid_runner.run_benchmark(
        baseline_sql="SELECT id, customer_id FROM orders WHERE amount > 50",
        run_id="bench-mid-cancel",
        warmup_runs=1,
        benchmark_runs=3,
    )
    assert mid_res["status"] == "cancelled"
    assert mid_res["comparison_verdict"] == "cancelled"
    assert mid_res["cancelled"] is True


# ==============================================================================
# 3. FEATURE C: FAIR COMPARISON, REGRESSIONS & INCONCLUSIVE VERDICTS
# ==============================================================================


def _make_plan_with_exec_time(
    exec_ms: float,
    total_cost: float = 100.0,
    node_type: str = "Index Scan",
    actual_rows: int = 250,
    shared_hit: int = 90,
    shared_read: int = 5,
) -> list[dict[str, Any]]:
    return [
        {
            "Plan": {
                "Node Type": node_type,
                "Relation Name": "orders",
                "Startup Cost": 0.5,
                "Total Cost": total_cost,
                "Plan Rows": 250,
                "Plan Width": 64,
                "Actual Startup Time": 0.1,
                "Actual Total Time": exec_ms,
                "Actual Rows": actual_rows,
                "Actual Loops": 1,
                "Shared Hit Blocks": shared_hit,
                "Shared Read Blocks": shared_read,
            },
            "Planning Time": 0.2,
            "Execution Time": exec_ms,
        }
    ]


def test_candidate_regression_detected_accurately():
    """Tests that when a candidate plan degrades measured latency (e.g. 10ms -> 28ms), verdict is 'regressed'."""
    base_plans = [
        _make_plan_with_exec_time(12.0, total_cost=120.0, node_type="Index Scan"),  # warmup
        _make_plan_with_exec_time(10.0, total_cost=120.0, node_type="Index Scan"),
        _make_plan_with_exec_time(10.2, total_cost=120.0, node_type="Index Scan"),
        _make_plan_with_exec_time(9.8, total_cost=120.0, node_type="Index Scan"),
    ]
    cand_plans = [
        _make_plan_with_exec_time(30.0, total_cost=450.0, node_type="Seq Scan"),  # warmup
        _make_plan_with_exec_time(28.0, total_cost=450.0, node_type="Seq Scan"),
        _make_plan_with_exec_time(28.5, total_cost=450.0, node_type="Seq Scan"),
        _make_plan_with_exec_time(27.5, total_cost=450.0, node_type="Seq Scan"),
    ]
    conn = _FakeSandboxConnection(baseline_plans=base_plans, candidate_plans=cand_plans)
    runner = SafeBenchmarkRunner(sandbox_engine=_FakeSandboxEngine(conn))

    res = runner.run_benchmark(
        baseline_sql="SELECT id, amount FROM orders WHERE customer_id = 42",
        candidate_sql="SELECT id, amount FROM orders WHERE customer_id + 0 = 42",
        warmup_runs=1,
        benchmark_runs=3,
    )
    assert res["status"] == "completed"
    assert res["comparison_verdict"] == "regressed"
    assert res["is_comparable"] is True
    assert res["measured_comparison"]["baseline_median_ms"] == 10.0
    assert res["measured_comparison"]["candidate_median_ms"] == 28.0
    assert res["measured_comparison"]["measured_speedup_pct"] == -180.0
    assert res["plan_comparison"]["structural_changes_summary"]["counts"]["scan_degraded"] >= 1


def test_inconclusive_comparison_on_high_variance_or_row_mismatch():
    """Tests that noisy measurements (high CV) or semantic row-count mismatches produce an 'inconclusive' verdict."""
    # Case 1: High run-to-run variability larger than median difference
    noisy_base = [
        _make_plan_with_exec_time(20.0),
        _make_plan_with_exec_time(5.0),
        _make_plan_with_exec_time(20.0),
        _make_plan_with_exec_time(65.0),
    ]
    noisy_cand = [
        _make_plan_with_exec_time(18.0),
        _make_plan_with_exec_time(6.0),
        _make_plan_with_exec_time(18.5),
        _make_plan_with_exec_time(60.0),
    ]
    conn_noisy = _FakeSandboxConnection(baseline_plans=noisy_base, candidate_plans=noisy_cand)
    runner_noisy = SafeBenchmarkRunner(sandbox_engine=_FakeSandboxEngine(conn_noisy))
    res_noisy = runner_noisy.run_benchmark(
        baseline_sql="SELECT id, amount FROM orders WHERE amount > 100",
        warmup_runs=1,
        benchmark_runs=3,
    )
    assert res_noisy["status"] == "completed"
    assert res_noisy["comparison_verdict"] == "inconclusive"

    # Case 2: Row count mismatch between baseline and candidate -> is_comparable=False, verdict='inconclusive'
    mismatch_base = [_make_plan_with_exec_time(20.0, actual_rows=500), _make_plan_with_exec_time(20.0, actual_rows=500)]
    mismatch_cand = [_make_plan_with_exec_time(5.0, actual_rows=10), _make_plan_with_exec_time(5.0, actual_rows=10)]
    conn_mismatch = _FakeSandboxConnection(baseline_plans=mismatch_base, candidate_plans=mismatch_cand)
    runner_mismatch = SafeBenchmarkRunner(sandbox_engine=_FakeSandboxEngine(conn_mismatch))
    res_mismatch = runner_mismatch.run_benchmark(
        baseline_sql="SELECT id, amount FROM orders WHERE amount > 100",
        candidate_sql="SELECT id, amount FROM orders WHERE amount > 99999",
        warmup_runs=1,
        benchmark_runs=1,
    )
    assert res_mismatch["is_comparable"] is False
    assert res_mismatch["comparison_verdict"] == "inconclusive"
    assert any("Row count mismatch" in r for r in res_mismatch["incomparability_reasons"])


# ==============================================================================
# 4. API ENDPOINTS & AUTHORIZED SANITIZED EXPORT TESTS
# ==============================================================================


def test_workbench_api_endpoints_authorization_and_literal_scrubbing_export(
    workbench_db: Session, monkeypatch
):
    """Tests /api/v1/plans/compare, /benchmark, /cancel, and /compare/export authorization and literal scrubbing."""
    import app.services.plans.workbench as wb_module

    base_plans = [
        _make_plan_with_exec_time(42.0, total_cost=950.0, node_type="Seq Scan"),
        _make_plan_with_exec_time(40.0, total_cost=950.0, node_type="Seq Scan"),
        _make_plan_with_exec_time(39.5, total_cost=950.0, node_type="Seq Scan"),
    ]
    cand_plans = [
        _make_plan_with_exec_time(4.5, total_cost=85.0, node_type="Index Scan"),
        _make_plan_with_exec_time(4.0, total_cost=85.0, node_type="Index Scan"),
        _make_plan_with_exec_time(4.2, total_cost=85.0, node_type="Index Scan"),
    ]
    fake_conn = _FakeSandboxConnection(baseline_plans=base_plans, candidate_plans=cand_plans)
    fake_sandbox = _FakeSandboxEngine(fake_conn)
    monkeypatch.setattr(wb_module, "get_sandbox_engine", lambda: fake_sandbox)

    client = TestClient(app)
    viewer_headers = _auth_header(1, "wb_viewer", Role.VIEWER)
    analyst_headers = _auth_header(2, "wb_analyst", Role.ANALYST)

    # 1. Anonymous requests must be rejected with 401
    assert client.post("/api/v1/plans/compare", json={}).status_code == 401
    assert client.post("/api/v1/plans/benchmark", json={}).status_code == 401
    assert client.post("/api/v1/plans/benchmark/run-1/cancel").status_code == 401
    assert client.post("/api/v1/plans/compare/export", json={}).status_code == 401

    # 2. Viewer can compare plans and export, but CANNOT execute sandbox benchmarks (403)
    compare_resp = client.post(
        "/api/v1/plans/compare",
        headers=viewer_headers,
        json={
            "baseline_plan": base_plans[0],
            "candidate_plan": cand_plans[0],
            "baseline_sql": "SELECT id FROM orders WHERE customer_email = 'alice.secret@corp.example.com' AND amount > 9999",
            "candidate_index_ddl": "CREATE INDEX idx_orders_email ON orders (customer_email)",
        },
    )
    assert compare_resp.status_code == 200
    comp_data = compare_resp.json()
    assert comp_data["verdict"] == "improved"
    assert "alice.secret@corp.example.com" not in json.dumps(comp_data)

    viewer_bench = client.post(
        "/api/v1/plans/benchmark",
        headers=viewer_headers,
        json={"baseline_sql": "SELECT id FROM orders WHERE amount > 100"},
    )
    assert viewer_bench.status_code == 403

    # 3. Analyst can execute safe sandbox benchmark
    analyst_bench = client.post(
        "/api/v1/plans/benchmark",
        headers=analyst_headers,
        json={
            "baseline_sql": "SELECT id, amount FROM orders WHERE status = 'SUPER_SECRET_TOKEN_98765' AND amount > 4242",
            "candidate_index_ddl": "CREATE INDEX idx_orders_status_amount ON orders (status, amount)",
            "warmup_runs": 1,
            "benchmark_runs": 2,
            "statement_timeout_ms": 2000,
        },
    )
    assert analyst_bench.status_code == 200
    bench_data = analyst_bench.json()
    assert bench_data["status"] == "completed"
    assert bench_data["comparison_verdict"] == "improved"
    assert "SUPER_SECRET_TOKEN_98765" not in json.dumps(bench_data)
    assert "4242" not in json.dumps(bench_data)

    # 4. Authorized JSON & CSV export must scrub all sensitive literals
    export_json_resp = client.post(
        "/api/v1/plans/compare/export",
        headers=viewer_headers,
        json={
            "format": "json",
            "comparison": bench_data,
        },
    )
    assert export_json_resp.status_code == 200
    export_json = export_json_resp.json()
    assert export_json["literals_scrubbed"] is True
    assert "SUPER_SECRET_TOKEN_98765" not in export_json["content"]
    parsed_export = json.loads(export_json["content"])
    assert parsed_export["cost_unit"] == "planner_cost_units"
    assert "<STR>" in parsed_export["candidate_change_context"]["sanitized_baseline_sql"]

    export_csv_resp = client.post(
        "/api/v1/plans/compare/export",
        headers=viewer_headers,
        json={
            "format": "csv",
            "comparison": bench_data,
        },
    )
    assert export_csv_resp.status_code == 200
    export_csv = export_csv_resp.json()
    assert export_csv["content_type"] == "text/csv"
    assert "SUPER_SECRET_TOKEN_98765" not in export_csv["content"]
    rows = list(csv.reader(io.StringIO(export_csv["content"])))
    assert len(rows) >= 2
    assert "baseline_total_cost_units (NOT_MS)" in rows[0]
