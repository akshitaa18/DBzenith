"""Comprehensive test suite for safe SQL AST rewriting in DBZenith.

Covers:
1. Strict contract compliance (7 mandatory fields in every rewrite).
2. AST transformations (OR_TO_IN_LIST, EXISTS_SELECT_ONE, IN_SUBQUERY_ORDER_BY, LEFT_JOIN_TO_INNER, REDUNDANT_DISTINCT).
3. Semantic regression verification (data equivalence between original and rewritten SQL).
4. Safety policy rejections (DML, DDL, volatile/non-deterministic functions, altered projections).
5. Sandbox validation (EXPLAIN cost comparison, regression detection).
6. Integration with QueryRewriteAdvisor and RL environment.
7. FastAPI endpoint verification.
"""

from __future__ import annotations

import sqlite3
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import app
from app.models.workload import QueryStatistic
from app.services.recommendations.query_rewrite import QueryRewriteAdvisor
from app.services.rewriter.ast_transformer import SQLASTTransformer
from app.services.rewriter.contracts import (
    SQLRewriteResult,
    TransformationType,
    ValidationStatus,
)
from app.services.rewriter.engine import SQLRewriteEngine, get_rewrite_engine
from app.services.rewriter.safety import SQLRewriteSafetyPolicy
from app.services.rewriter.sandbox_validator import SandboxRewriteValidator
from app.services.rl.contracts import ActionType
from app.services.rl.environment import DatabaseOptimizationEnv


# =========================================================================
# 1. Mandatory Contract Verification
# =========================================================================

def test_mandatory_seven_attributes_presence():
    """Verify every SQLRewriteResult contains all 7 mandated fields."""
    engine = SQLRewriteEngine()
    sql = "SELECT order_id, customer_id FROM orders WHERE status = 'shipped' OR status = 'delivered'"
    res = engine.rewrite(sql, validate_sandbox=False)

    # 1. original query
    assert hasattr(res, "original_query") and len(res.original_query) > 0
    # 2. rewritten query
    assert hasattr(res, "rewritten_query") and len(res.rewritten_query) > 0
    # 3. transformation
    assert hasattr(res, "transformation") and res.transformation == TransformationType.OR_TO_IN_LIST.value
    # 4. reason
    assert hasattr(res, "reason") and len(res.reason) > 0
    # 5. expected benefit
    assert hasattr(res, "expected_benefit") and len(res.expected_benefit) > 0
    # 6. confidence
    assert hasattr(res, "confidence") and 0.0 <= res.confidence <= 1.0
    # 7. validation status
    assert hasattr(res, "validation_status") and res.validation_status in [s.value for s in ValidationStatus]

    # Invariant: production is never modified
    assert res.production_modified is False


# =========================================================================
# 2. Conservative AST Transformations
# =========================================================================

def test_ast_or_to_in_list():
    transformer = SQLASTTransformer()
    sql = "SELECT id, total FROM orders WHERE id = 10 OR id = 20 OR id = 30"
    transformed, applied, diff, reason, benefit = transformer.transform(sql)

    assert applied == TransformationType.OR_TO_IN_LIST
    assert "IN (10, 20, 30)" in transformed
    assert " OR " not in transformed.upper()
    assert "chained or equality" in reason.lower()


def test_ast_exists_select_one_simplification():
    transformer = SQLASTTransformer()
    sql = "SELECT id FROM orders o WHERE EXISTS (SELECT * FROM items i WHERE i.order_id = o.id)"
    transformed, applied, diff, reason, benefit = transformer.transform(sql)

    assert applied == TransformationType.EXISTS_SELECT_ONE_SIMPLIFICATION
    assert "SELECT 1 FROM items" in transformed
    assert "SELECT *" not in transformed


def test_ast_in_subquery_order_by_elimination():
    transformer = SQLASTTransformer()
    sql = "SELECT customer_name FROM customers WHERE id IN (SELECT customer_id FROM orders ORDER BY order_date DESC)"
    transformed, applied, diff, reason, benefit = transformer.transform(sql)

    assert applied == TransformationType.IN_SUBQUERY_ORDER_BY_ELIMINATION
    assert "ORDER BY" not in transformed
    assert "redundant order by" in reason.lower()


def test_ast_left_join_to_inner_join():
    transformer = SQLASTTransformer()
    sql = "SELECT o.id, c.name FROM orders o LEFT JOIN customers c ON o.customer_id = c.id WHERE c.name = 'VIP'"
    transformed, applied, diff, reason, benefit = transformer.transform(sql)

    assert applied == TransformationType.LEFT_JOIN_TO_INNER_JOIN
    assert "JOIN customers" in transformed
    assert "LEFT JOIN" not in transformed.upper()


def test_ast_redundant_distinct_elimination():
    transformer = SQLASTTransformer()
    sql = "SELECT DISTINCT customer_id, count(*) FROM orders GROUP BY customer_id"
    transformed, applied, diff, reason, benefit = transformer.transform(sql)

    assert applied == TransformationType.REDUNDANT_DISTINCT_ELIMINATION
    assert "DISTINCT" not in transformed.upper()
    assert "GROUP BY customer_id" in transformed


def test_no_transformation_when_already_optimal():
    transformer = SQLASTTransformer()
    sql = "SELECT id, name FROM users WHERE id = 1"
    transformed, applied, diff, reason, benefit = transformer.transform(sql)

    assert applied == TransformationType.NO_OP
    assert transformed == sql


# =========================================================================
# 3. Safety Policy Rejections
# =========================================================================

def test_safety_rejects_dml():
    policy = SQLRewriteSafetyPolicy()
    for dml in [
        "UPDATE orders SET status = 'cancelled' WHERE id = 1",
        "DELETE FROM orders WHERE id = 1",
        "INSERT INTO orders (id, total) VALUES (1, 100.0)",
    ]:
        safe, reason = policy.check_query_safety(dml)
        assert safe is False
        assert "Non-SELECT or DML statement detected" in reason


def test_safety_rejects_ddl():
    policy = SQLRewriteSafetyPolicy()
    for ddl in [
        "DROP TABLE orders",
        "CREATE TABLE test (id int)",
        "ALTER TABLE orders ADD COLUMN extra text",
        "TRUNCATE TABLE orders",
    ]:
        safe, reason = policy.check_query_safety(ddl)
        assert safe is False
        assert "Non-SELECT or DML statement detected" in reason or "Invalid SQL" in reason


def test_ast_left_join_preserved_on_anti_join_is_null():
    transformer = SQLASTTransformer()
    sql = "SELECT c.id FROM customers c LEFT JOIN orders o ON c.id = o.customer_id WHERE o.id IS NULL"
    transformed, applied, diff, reason, benefit = transformer.transform(sql)
    assert applied == TransformationType.NO_OP
    assert "LEFT JOIN" in transformed.upper()


def test_ast_distinct_preserved_when_group_by_not_fully_projected():
    transformer = SQLASTTransformer()
    sql = "SELECT DISTINCT status FROM orders GROUP BY customer_id, status"
    transformed, applied, diff, reason, benefit = transformer.transform(sql)
    assert applied == TransformationType.NO_OP
    assert "DISTINCT" in transformed.upper()


def test_safety_rejects_volatile_and_nondeterministic_functions():
    policy = SQLRewriteSafetyPolicy()
    for volatile_query in [
        "SELECT id, random() FROM orders",
        "SELECT id, clock_timestamp() FROM orders",
        "SELECT id, txid_current() FROM orders",
        "SELECT pg_sleep(5)",
        "SELECT pg_read_file('/etc/passwd')",
    ]:
        safe, reason = policy.check_query_safety(volatile_query)
        assert safe is False
        assert "volatile" in reason.lower()



def test_safety_rejects_column_projection_alterations():
    policy = SQLRewriteSafetyPolicy()
    orig = "SELECT id, customer_id, status FROM orders WHERE id = 1"
    # An unsafe rewrite that drops or adds projection columns
    unsafe_rewrite = "SELECT id FROM orders WHERE id = 1"
    safe, reason = policy.validate_rewrite_safety(orig, unsafe_rewrite)
    assert safe is False
    assert "Projection column count mismatch" in reason


def test_rewriter_engine_returns_unsafe_rejected_result():
    engine = SQLRewriteEngine()
    dml = "DELETE FROM telemetry_demo_orders WHERE order_id = 99"
    res = engine.rewrite(dml, validate_sandbox=False)

    assert res.validation_status == ValidationStatus.UNSAFE_REJECTED.value
    assert res.safety_verdict == "unsafe"
    assert res.confidence == 0.0
    assert "Non-SELECT or DML" in res.reason
    assert res.production_modified is False


# =========================================================================
# 4. Semantic Regression Verification
# =========================================================================

def test_semantic_regression_validation_match():
    """Verify SandboxRewriteValidator confirms semantic match on identical result rows."""
    # Create an in-memory SQLite database simulating sandbox relation
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE items (id INT, order_id INT, price REAL);"))
        conn.execute(text("INSERT INTO items VALUES (1, 101, 15.0), (2, 102, 25.0), (3, 101, 35.0);"))

    validator = SandboxRewriteValidator()
    q_orig = "SELECT id, order_id FROM items WHERE id = 1 OR id = 2 ORDER BY id"
    q_rewritten = "SELECT id, order_id FROM items WHERE id IN (1, 2) ORDER BY id"

    res = validator.validate_rewrite(q_orig, q_rewritten, engine_override=engine)
    assert res["validation_status"] == ValidationStatus.VALIDATED_IN_SANDBOX.value
    assert res["semantic_match"] is True


def test_semantic_regression_validation_detects_mismatch():
    """Verify SandboxRewriteValidator rejects rewrite if tuple output differs."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE items (id INT, category TEXT);"))
        conn.execute(text("INSERT INTO items VALUES (1, 'electronics'), (2, 'clothing');"))

    validator = SandboxRewriteValidator()
    q_orig = "SELECT id, category FROM items WHERE id = 1"
    # Rewritten query artificially changes condition -> semantic mismatch
    q_mismatched = "SELECT id, category FROM items WHERE id = 2"

    res = validator.validate_rewrite(q_orig, q_mismatched, engine_override=engine)
    assert res["validation_status"] == ValidationStatus.REJECTED_SEMANTIC_REGRESSION.value
    assert res["semantic_match"] is False
    assert "Semantic regression detected" in res["rejection_reason"]


# =========================================================================
# 5. Integration with Recommendation Engine
# =========================================================================

def test_query_rewrite_advisor_generates_ast_recommendation():
    """Test that QueryRewriteAdvisor incorporates SQLRewriteEngine to produce typed recommendations."""
    advisor = QueryRewriteAdvisor()
    q_stat = QueryStatistic(
        query_id=9876,
        normalized_query="SELECT order_id, customer_id FROM telemetry_demo_orders WHERE status = 'shipped' OR status = 'delivered'",
        total_exec_time_ms=1500.0,
        mean_exec_time_ms=75.0,
        calls=20,
        rows=100,
        shared_blks_hit=1000,
        shared_blks_read=50,
        temp_blks_read=0,
        temp_blks_written=0,
    )

    recs = advisor.advise([q_stat])
    assert len(recs) >= 1
    ast_rec = next(r for r in recs if "AST Rewrite" in r.proposed_change)
    assert ast_rec.type == "query_rewrite"
    assert ast_rec.requires_approval is True

    # Check evidence contains all 7 mandated properties
    ev = ast_rec.evidence
    assert "original_query" in ev
    assert "rewritten_query" in ev
    assert "transformation" in ev
    assert "reason" in ev
    assert "expected_benefit" in ev
    assert "confidence" in ev
    assert "validation_status" in ev
    assert "IN ('shipped', 'delivered')" in ev["rewritten_query"]


# =========================================================================
# 6. Integration with Reinforcement Learning
# =========================================================================

def test_rl_environment_rewrite_query_action():
    """Test that RL ActionType.REWRITE_QUERY utilizes the rewriter engine and obeys safety pipeline."""
    env = DatabaseOptimizationEnv()
    obs, info = env.reset()

    # Step with REWRITE_QUERY
    obs, reward, terminated, truncated, info = env.step(ActionType.REWRITE_QUERY)

    rec = info["recommendation"]
    assert rec["action_type"] == ActionType.REWRITE_QUERY.value
    assert "AST Rewrite" in rec["proposed_change"]
    assert rec["requires_approval"] is True

    # Check metadata includes rewrite contract details
    meta = rec["metadata"]
    assert "original_query" in meta
    assert "rewritten_query" in meta
    assert "transformation" in meta
    assert "reason" in meta
    assert "expected_benefit" in meta
    assert "confidence" in meta
    assert "validation_status" in meta

    # Sandbox measurement
    meas = info["measured_result"]
    assert meas["sandbox_status"] == "success"
    assert meas["latency_improvement_pct"] > 0
    assert info["production_modified"] is False


# =========================================================================
# 7. FastAPI Endpoint Verification
# =========================================================================

def _with_isolated_db():
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db.base import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_api_rewrite_endpoint():
    from app.core.security import Role, get_security_manager
    from app.db.session import get_db

    session = _with_isolated_db()
    app.dependency_overrides[get_db] = lambda: session
    try:
        client = TestClient(app)
        token = get_security_manager().create_token("2", "analyst_user", Role.ANALYST)
        req_body = {
            "sql": "SELECT id, price FROM products WHERE category = 'books' OR category = 'music'",
            "validate_sandbox": False,
        }
        resp = client.post(
            "/api/v1/rewriter/rewrite",
            headers={"Authorization": f"Bearer {token}"},
            json=req_body,
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["original_query"] == req_body["sql"]
        assert "IN ('books', 'music')" in data["rewritten_query"]
        assert data["transformation"] == TransformationType.OR_TO_IN_LIST.value
        assert len(data["reason"]) > 0
        assert len(data["expected_benefit"]) > 0
        assert data["confidence"] > 0.0
        assert data["validation_status"] == ValidationStatus.PENDING.value
        assert data["production_modified"] is False
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_api_rewrite_endpoint_rejects_unsafe():
    from app.core.security import Role, get_security_manager
    from app.db.session import get_db

    session = _with_isolated_db()
    app.dependency_overrides[get_db] = lambda: session
    try:
        client = TestClient(app)
        token = get_security_manager().create_token("2", "analyst_user", Role.ANALYST)
        req_body = {
            "sql": "DROP TABLE accounts;",
            "validate_sandbox": False,
        }
        resp = client.post(
            "/api/v1/rewriter/rewrite",
            headers={"Authorization": f"Bearer {token}"},
            json=req_body,
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["validation_status"] == ValidationStatus.UNSAFE_REJECTED.value
        assert data["safety_verdict"] == "unsafe"
        assert data["production_modified"] is False
    finally:
        app.dependency_overrides.clear()
        session.close()

