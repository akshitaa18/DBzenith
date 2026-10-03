import json

from app.services.plans.analyzer import analyze_plan
from app.services.plans.parser import parse_plan
from app.services.plans.sanitizer import sanitize_raw_plan
from app.services.privacy.contracts import RawPlan


def plan_fixture():
    return [{"Plan": {
        "Node Type": "Nested Loop",
        "Startup Cost": 0.0,
        "Total Cost": 250.0,
        "Plan Rows": 10,
        "Actual Rows": 1000,
        "Actual Loops": 200,
        "Actual Total Time": 140.0,
        "Plans": [
            {"Node Type": "Seq Scan", "Relation Name": "users", "Plan Rows": 10, "Actual Rows": 500, "Actual Loops": 1, "Actual Total Time": 12.0,
             "Filter": "email = 'alice@example.com' AND age > 42", "Rows Removed by Filter": 4500},
            {"Node Type": "Hash Join", "Plan Rows": 100, "Actual Rows": 1200, "Actual Loops": 1, "Actual Total Time": 40.0,
             "Plans": [
                 {"Node Type": "Bitmap Heap Scan", "Relation Name": "orders", "Plan Rows": 20, "Actual Rows": 400, "Actual Loops": 1, "Actual Total Time": 8.0},
                 {"Node Type": "Index Scan", "Relation Name": "customers", "Index Name": "customers_email_idx", "Plan Rows": 20, "Actual Rows": 20, "Actual Loops": 1, "Actual Total Time": 2.0},
             ]},
        ],
    }}]


def test_plan_parser_builds_graph_for_multiple_node_types():
    graph = parse_plan(plan_fixture())
    types = {n.node_type for n in graph.nodes.values()}
    assert {"Nested Loop", "Seq Scan", "Hash Join", "Bitmap Heap Scan", "Index Scan"} <= types
    assert len(graph.edges) == 4


def test_plan_sanitizer_removes_sensitive_values_and_identifiers():
    safe = sanitize_raw_plan(RawPlan(plan=plan_fixture()))
    dumped = json.dumps(safe.model_dump())
    assert "alice@example.com" not in dumped
    assert " > 42" not in dumped and " = 42" not in dumped
    assert "users" not in dumped
    assert "customers_email_idx" not in dumped
    assert "Index Scan" in dumped


def test_analyzer_detects_requested_bottleneck_classes():
    result = analyze_plan(RawPlan(plan=plan_fixture()))
    types = {b["type"] for b in result["bottlenecks"]}
    assert "sequential_scan" in types
    assert "high_loop_count" in types
    assert "row_estimation_error" in types
    assert "filtering_inefficiency" in types
    assert result["features"]["nested_loops"] == 1
    assert result["features"]["hash_joins"] == 1
    assert result["features"]["bitmap_scans"] == 1
    assert result["features"]["index_scans"] == 1


def test_plan_analysis_response_is_sanitized():
    result = analyze_plan(RawPlan(plan=plan_fixture()))
    dumped = json.dumps(result, default=str)
    assert "alice@example.com" not in dumped
    assert "customers_email_idx" not in dumped
    assert "users" not in dumped
