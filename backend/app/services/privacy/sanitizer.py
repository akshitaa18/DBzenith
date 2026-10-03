from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Any

from app.services.privacy.contracts import RawPlan, RawQuery, SanitizedPlan, SanitizedQuery
from app.services.privacy.parser import SqlAst, SqlToken, parse_sql

_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "NULL", "IS", "IN", "LIKE", "ILIKE",
    "BETWEEN", "AS", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "CROSS", "ON",
    "GROUP", "BY", "ORDER", "HAVING", "LIMIT", "OFFSET", "FETCH", "UNION", "ALL", "DISTINCT",
    "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE", "RETURNING", "WITH", "RECURSIVE",
    "CASE", "WHEN", "THEN", "ELSE", "END", "EXISTS", "CAST", "COALESCE", "NULLIF", "ASC", "DESC",
    "NULLS", "FIRST", "LAST", "WINDOW", "OVER", "PARTITION", "FILTER", "CREATE", "ALTER", "DROP",
    "TABLE", "INDEX", "VIEW", "EXPLAIN", "ANALYZE", "TRUE", "FALSE", "FOR", "SHARE", "LOCK",
    "NOWAIT", "SKIP", "INTERSECT", "EXCEPT", "PRIMARY", "KEY", "REFERENCES", "CONSTRAINT", "DEFAULT",
}


def _token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def identifier_token(value: str) -> str:
    raw = value[1:-1].replace('""', '"') if value.startswith('"') else value
    return f"id_{_token(raw)}"


def _render_ast(ast: SqlAst, identifiers: list[str], counts: dict[str, int]) -> str:
    parts: list[str] = []
    for node in ast.nodes:
        if isinstance(node, SqlAst):
            parts.append(f"( {_render_ast(node, identifiers, counts)} )")
            continue
        token = node
        if token.kind == "STRING":
            counts["string"] = counts.get("string", 0) + 1
            parts.append("<STR>")
        elif token.kind == "NUMBER":
            counts["number"] = counts.get("number", 0) + 1
            parts.append("<NUM>")
        elif token.kind == "PARAM":
            counts["parameter"] = counts.get("parameter", 0) + 1
            parts.append("<PARAM>")
        elif token.kind == "SENSITIVE":
            counts["sensitive"] = counts.get("sensitive", 0) + 1
            parts.append("<SENSITIVE>")
        elif token.kind == "IDENTIFIER":
            t = identifier_token(token.value)
            identifiers.append(t)
            parts.append(t)
        elif token.kind == "WORD":
            upper = token.value.upper()
            if upper in _KEYWORDS:
                parts.append(upper)
            else:
                t = identifier_token(token.value)
                identifiers.append(t)
                parts.append(t)
        else:
            parts.append(token.value)
    return " ".join(parts)


def sanitize_query(raw: RawQuery) -> SanitizedQuery:
    ast = parse_sql(raw.sql)
    identifiers: list[str] = []
    counts: dict[str, int] = {}
    normalized = re.sub(r"\s+", " ", _render_ast(ast, identifiers, counts)).strip()
    statement_type = next((t.value.upper() for t in ast.iter_tokens() if t.kind == "WORD"), "UNKNOWN")
    structural_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return SanitizedQuery(
        normalized_sql=normalized,
        structural_hash=structural_hash,
        identifier_tokens=sorted(set(identifiers)),
        literal_counts=counts,
        statement_type=statement_type,
    )


_PLAN_EXPRESSION_KEYS = {
    "Filter", "Index Cond", "Recheck Cond", "Join Filter", "Hash Cond", "Merge Cond", "TID Cond",
    "Output", "Sort Key", "Group Key", "Partition Key", "Partition Constraint", "Index Cond",
}
_PLAN_SAFE_STRING_KEYS = {"Node Type", "Join Type", "Strategy", "Partial Mode", "Parent Relationship"}
_PLAN_RELATION_KEYS = {"Relation Name", "Schema", "Alias", "Index Name"}


def _sanitize_plan_value(value: Any, relation_tokens: list[str], operators: list[str], key: str = "") -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for child_key, item in value.items():
            if child_key in _PLAN_SAFE_STRING_KEYS and isinstance(item, str):
                if child_key == "Node Type":
                    operators.append(item)
                out[child_key] = item
            elif child_key in _PLAN_RELATION_KEYS:
                if isinstance(item, str):
                    token = identifier_token(item)
                    relation_tokens.append(token)
                    out[child_key] = token
                else:
                    out[child_key] = "<IDENTIFIER>"
            elif child_key in _PLAN_EXPRESSION_KEYS and isinstance(item, str):
                safe = sanitize_query(RawQuery(sql=f"SELECT 1 WHERE {item}")).normalized_sql
                out[child_key] = safe
            else:
                out[child_key] = _sanitize_plan_value(item, relation_tokens, operators, child_key)
        return out
    if isinstance(value, list):
        return [_sanitize_plan_value(v, relation_tokens, operators, key) for v in value]
    if isinstance(value, str):
        # Unknown EXPLAIN text is fail-closed. It is not needed by AI plan models.
        return value if key in _PLAN_SAFE_STRING_KEYS else "<TEXT>"
    return value


def sanitize_plan(raw: RawPlan) -> SanitizedPlan:
    operators: list[str] = []
    relation_tokens: list[str] = []
    safe = _sanitize_plan_value(raw.plan, relation_tokens, operators)
    canonical = repr(safe).encode("utf-8")
    return SanitizedPlan(
        plan=safe,
        structural_hash=hashlib.sha256(canonical).hexdigest(),
        operator_types=sorted(set(operators)),
        relation_tokens=sorted(set(relation_tokens)),
    )
