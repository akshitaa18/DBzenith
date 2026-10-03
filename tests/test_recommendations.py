from types import SimpleNamespace

from app.services.recommendations.join import JoinStrategyAdvisor
from app.services.recommendations.parsing import parse_query_shape
from app.services.recommendations.query_rewrite import QueryRewriteAdvisor


def q(**kwargs):
    defaults = dict(query_id=1, normalized_query="SELECT id FROM orders WHERE customer_id = $1 ORDER BY created_at DESC", total_exec_time_ms=2500.0, mean_exec_time_ms=50.0, calls=1000, query_frequency_per_minute=30.0, shared_blks_read=500, rows=100, temp_blks_read=0, temp_blks_written=0, explain_plan=None)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_query_shape_extracts_predicate_join_order_and_group():
    shape = parse_query_shape("SELECT o.id FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status = $1 GROUP BY o.status ORDER BY o.created_at DESC")
    assert ("orders", "status") in shape.where_columns
    assert ("orders", "customer_id") in shape.join_columns
    assert ("customers", "id") in shape.join_columns
    assert ("orders", "created_at", "DESC") in shape.order_columns
    assert "status" in shape.group_columns


def test_query_rewrite_advisor_is_deterministic_and_not_ml():
    recs = QueryRewriteAdvisor().advise([q(normalized_query="SELECT * FROM orders WHERE status = $1")])
    assert recs and recs[0].type == "query_rewrite"
    assert recs[0].requires_approval is True
    assert recs[0].confidence <= 1


def test_join_advisor_detects_high_loop_nested_loop():
    plan = [{"Plan": {"Node Type": "Nested Loop", "Actual Loops": 250, "Actual Total Time": 120.0, "Plans": []}}]
    recs = JoinStrategyAdvisor().advise([q(explain_plan=plan)])
    assert recs and recs[0].type == "join_strategy"
    assert "hash or merge" in recs[0].proposed_change.lower()
