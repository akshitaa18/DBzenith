from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryShape:
    relations: list[str]
    aliases: dict[str, str]
    where_columns: list[tuple[str, str]]
    join_columns: list[tuple[str, str]]
    order_columns: list[tuple[str, str]]
    group_columns: list[str]
    select_star: bool


_ALIAS_EXCLUSIONS = {
    "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "FULL", "CROSS",
    "ON", "ORDER", "GROUP", "LIMIT", "OFFSET", "HAVING", "UNION", "SET", "VALUES",
}
_COLUMN_EXCLUSIONS = {
    "EXISTS", "NOT", "AND", "OR", "NULL", "TRUE", "FALSE", "CASE", "WHEN",
    "THEN", "ELSE", "END", "SUM", "COUNT", "AVG", "MIN", "MAX", "COALESCE",
    "EXTRACT", "DATE_TRUNC", "BETWEEN", "IN", "IS", "LIKE", "ILIKE",
    "SELECT", "FROM", "WHERE", "GROUP", "ORDER", "BY", "ASC", "DESC",
    "LIMIT", "OFFSET", "HAVING", "DISTINCT", "AS", "ON", "JOIN", "LEFT",
    "RIGHT", "INNER", "OUTER",
}
_VALID_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _clean_identifier(value: str) -> str:
    return value.strip().strip('"')


def _is_valid_column(col: str) -> bool:
    if not col or not _VALID_IDENT.match(col):
        return False
    return col.upper() not in _COLUMN_EXCLUSIONS


def parse_query_shape(sql: str) -> QueryShape:
    text = re.sub(r"/\*.*?\*/|--[^\n]*", " ", sql, flags=re.S)
    # Strip single-quoted string literals so values like 'pending' or 'processing' are not parsed as columns
    text_no_literals = re.sub(r"'[^']*'", "''", text)
    relations: list[str] = []
    aliases: dict[str, str] = {}
    for match in re.finditer(r"\b(?:FROM|JOIN)\s+([\w\".]+)(?:\s+(?:AS\s+)?([\w\"]+))?", text_no_literals, re.I):
        rel = _clean_identifier(match.group(1).split('.')[-1])
        if rel.upper() in _ALIAS_EXCLUSIONS or not _VALID_IDENT.match(rel):
            continue
        alias = _clean_identifier(match.group(2)) if match.group(2) else rel
        if alias.upper() in _ALIAS_EXCLUSIONS:
            alias = rel
        if rel not in relations:
            relations.append(rel)
        aliases[alias] = rel

    def resolve(token: str) -> tuple[str, str]:
        token = token.strip().strip('"')
        if "." in token:
            a, col = token.split(".", 1)
            return aliases.get(_clean_identifier(a), _clean_identifier(a)), _clean_identifier(col)
        rel = relations[0] if relations else "unknown_relation"
        return rel, _clean_identifier(token)

    where_columns: list[tuple[str, str]] = []
    where_match = re.search(r"\bWHERE\b(.*?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bOFFSET\b|$)", text_no_literals, re.I | re.S)
    if where_match:
        for m in re.finditer(
            r"\b([A-Za-z_\"][\w\"]*(?:\.[A-Za-z_\"][\w\"]*)?)\s*(?:=|<|>|<=|>=|<>|!=|\b(?:LIKE|ILIKE|IN|IS)\b)",
            where_match.group(1),
            re.I,
        ):
            rel, col = resolve(m.group(1))
            if _is_valid_column(col):
                where_columns.append((rel, col))

    join_columns: list[tuple[str, str]] = []
    for m in re.finditer(r"\bON\s+([\w\"]+(?:\.[\w\"]+)?)\s*=\s*([\w\"]+(?:\.[\w\"]+)?)", text_no_literals, re.I):
        left = resolve(m.group(1))
        right = resolve(m.group(2))
        if _is_valid_column(left[1]):
            join_columns.append(left)
        if _is_valid_column(right[1]):
            join_columns.append(right)

    order_columns: list[tuple[str, str, str]] = []
    order_match = re.search(r"\bORDER\s+BY\s+(.*?)(?:\bLIMIT\b|\bOFFSET\b|$)", text_no_literals, re.I | re.S)
    if order_match:
        for item in order_match.group(1).split(','):
            stripped_item = item.strip()
            if "(" in stripped_item or ")" in stripped_item:
                continue
            m = re.match(r"^\s*([\w\"]+(?:\.[\w\"]+)?)(?:\s+(ASC|DESC))?\s*$", stripped_item, re.I)
            if m:
                rel, col = resolve(m.group(1))
                if _is_valid_column(col):
                    order_columns.append((rel, col, (m.group(2) or "ASC").upper()))

    group_columns: list[str] = []
    group_match = re.search(r"\bGROUP\s+BY\s+(.*?)(?:\bHAVING\b|\bORDER\s+BY\b|\bLIMIT\b|\bOFFSET\b|$)", text_no_literals, re.I | re.S)
    if group_match:
        for item in group_match.group(1).split(','):
            stripped_item = item.strip()
            if not stripped_item or "(" in stripped_item or ")" in stripped_item:
                continue
            col = resolve(stripped_item.split()[0])[1]
            if _is_valid_column(col):
                group_columns.append(col)

    select_match = re.match(r"\s*SELECT\s+(.*?)\s+FROM\b", text_no_literals, re.I | re.S)
    select_star = bool(select_match and "*" in select_match.group(1))
    return QueryShape(relations, aliases, where_columns, join_columns, order_columns, group_columns, select_star)
