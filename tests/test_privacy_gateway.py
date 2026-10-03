import json

import pytest

from app.services.ai.boundary import AIBoundaryValidator
from app.services.privacy.contracts import AIWorkloadRecord, RawPlan, RawQuery
from app.services.privacy.gateway import PrivacyGateway
from app.services.privacy.parser import parse_sql, tokenize_sql


@pytest.fixture
def gateway() -> PrivacyGateway:
    return PrivacyGateway()


def sanitize(gateway: PrivacyGateway, sql: str) -> str:
    return gateway.sanitize_query(RawQuery(sql=sql)).normalized_sql


@pytest.mark.parametrize(
    ("name", "sql", "forbidden"),
    [
        ("email", "SELECT * FROM users WHERE email = 'alice@example.com'", "alice@example.com"),
        ("phone", "SELECT * FROM users WHERE phone = '+91 98765 43210'", "+91 98765 43210"),
        ("uuid", "SELECT * FROM users WHERE id = '550e8400-e29b-41d4-a716-446655440000'", "550e8400-e29b-41d4-a716-446655440000"),
        ("number", "SELECT * FROM users WHERE age > 42 AND balance = 12345.67", "42"),
        ("string", "SELECT * FROM users WHERE name = 'Alice'", "Alice"),
        ("ip", "SELECT * FROM logins WHERE ip = '192.168.10.15'", "192.168.10.15"),
        ("password", "SELECT * FROM users WHERE password = 'SuperSecretPassword123!'", "SuperSecretPassword123!"),
        ("api_key", "SELECT * FROM clients WHERE api_key = 'sk_test_1234567890abcdef'", "sk_test_1234567890abcdef"),
        ("comment", "SELECT * FROM users -- alice@example.com 42\nWHERE id = 7", "alice@example.com"),
        ("json", "SELECT * FROM events WHERE payload = '{\"email\":\"alice@example.com\",\"age\":42}'", "alice@example.com"),
        ("nested", "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders WHERE total > 9000)", "9000"),
    ],
)
def test_sensitive_literals_are_removed(gateway: PrivacyGateway, name: str, sql: str, forbidden: str) -> None:
    result = sanitize(gateway, sql)
    assert f" {forbidden} " not in f" {result} "
    assert "<" in result


def test_nested_sql_is_structurally_preserved(gateway: PrivacyGateway) -> None:
    result = sanitize(gateway, "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders WHERE total > 9000)")
    assert "SELECT" in result
    assert "(" in result and ")" in result
    assert "<NUM>" in result


def test_comments_are_not_preserved(gateway: PrivacyGateway) -> None:
    result = sanitize(gateway, "SELECT * FROM users /* password=SuperSecretPassword123 */ WHERE age = 42")
    assert "password" not in result.lower()
    assert "SuperSecretPassword123" not in result
    assert "<NUM>" in result


def test_structural_hash_is_value_independent(gateway: PrivacyGateway) -> None:
    a = gateway.sanitize_query(RawQuery(sql="SELECT * FROM users WHERE age = 42"))
    b = gateway.sanitize_query(RawQuery(sql="SELECT * FROM users WHERE age = 99"))
    assert a.structural_hash == b.structural_hash
    assert a.normalized_sql == b.normalized_sql


def test_different_structure_changes_hash(gateway: PrivacyGateway) -> None:
    a = gateway.sanitize_query(RawQuery(sql="SELECT * FROM users WHERE age = 42"))
    b = gateway.sanitize_query(RawQuery(sql="SELECT * FROM users WHERE age > 42"))
    assert a.structural_hash != b.structural_hash


def test_schema_identifiers_are_tokenized(gateway: PrivacyGateway) -> None:
    result = sanitize(gateway, "SELECT email FROM customer_accounts WHERE id = 42")
    assert "customer_accounts" not in result
    assert "email" not in result
    assert "customer_accounts" not in result
    assert "email" not in result
    assert "id_" in result


def test_parser_rejects_unbalanced_sql(gateway: PrivacyGateway) -> None:
    with pytest.raises(ValueError):
        gateway.sanitize_query(RawQuery(sql="SELECT * FROM users WHERE id IN (SELECT id FROM users"))


def test_plan_sanitization_removes_filter_literals(gateway: PrivacyGateway) -> None:
    raw = RawPlan(
        plan=[
            {
                "Plan": {
                    "Node Type": "Index Scan",
                    "Relation Name": "users",
                    "Filter": "(email = 'alice@example.com' AND age > 42)",
                    "Actual Rows": 5,
                }
            }
        ]
    )
    safe = gateway.sanitize_plan(raw)
    dumped = json.dumps(safe.model_dump())
    assert "alice@example.com" not in dumped
    assert '"Filter": "SELECT <NUM> WHERE' in dumped
    assert "users" not in dumped
    assert "Index Scan" in dumped


def test_ai_boundary_rejects_raw_contracts(gateway: PrivacyGateway) -> None:
    validator = AIBoundaryValidator()
    raw = RawQuery(sql="SELECT * FROM users WHERE email = 'alice@example.com'")
    with pytest.raises(TypeError):
        validator.validate(raw)  # type: ignore[arg-type]


def test_ai_record_contains_only_sanitized_contracts(gateway: PrivacyGateway) -> None:
    record = gateway.build_ai_record(
        RawQuery(sql="SELECT * FROM users WHERE email = 'alice@example.com'"),
        calls=10,
        query_frequency_per_minute=5.0,
        duration_ms_bucket=100,
        rows_bucket=10,
        sample_count=1,
    )
    assert isinstance(record, AIWorkloadRecord)
    dumped = json.dumps(record.model_dump())
    assert "alice@example.com" not in dumped
    AIBoundaryValidator().validate(record)


def test_tokenizer_drops_comments_and_classifies_literals() -> None:
    tokens = tokenize_sql("SELECT * FROM users -- secret\nWHERE age = 42 AND email = 'alice@example.com'")
    assert all("secret" not in token.value for token in tokens)
    assert any(token.kind == "NUMBER" for token in tokens)
    assert any(token.kind == "STRING" for token in tokens)


def test_ast_has_nested_groups() -> None:
    ast = parse_sql("SELECT * FROM users WHERE id IN (SELECT id FROM orders WHERE total > 10)")
    assert len(ast.nodes) > 0
    groups = [node for node in ast.nodes if hasattr(node, "nodes")]
    assert len(groups) == 1
    assert groups[0].nodes
