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


def _clean_identifier(value: str) -> str:
    return value.strip().strip('"')


def parse_query_shape(sql: str) -> QueryShape:
    text = re.sub(r"/\*.*?\*/|--[^\n]*", " ", sql, flags=re.S)
    relations: list[str] = []
    aliases: dict[str, str] = {}
    for match in re.finditer(r"\b(?:FROM|JOIN)\s+([\w\".]+)(?:\s+(?:AS\s+)?([\w\"]+))?", text, re.I):
        rel = _clean_identifier(match.group(1).split('.')[-1])
        alias = _clean_identifier(match.group(2)) if match.group(2) else rel
        if alias.upper() not in {"WHERE", "JOIN", "ON", "ORDER", "GROUP", "LIMIT", "OFFSET"}:
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
    where_match = re.search(r"\bWHERE\b(.*?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bOFFSET\b|$)", text, re.I | re.S)
    if where_match:
        for m in re.finditer(r"([\w\"]+(?:\.[\w\"]+)?)\s*(?:=|<|>|<=|>=|<>|!=|LIKE|ILIKE|IN|IS)", where_match.group(1), re.I):
            where_columns.append(resolve(m.group(1)))

    join_columns: list[tuple[str, str]] = []
    for m in re.finditer(r"\bON\s+([\w\"]+(?:\.[\w\"]+)?)\s*=\s*([\w\"]+(?:\.[\w\"]+)?)", text, re.I):
        left = resolve(m.group(1))
        right = resolve(m.group(2))
        join_columns.extend([left, right])

    order_columns: list[tuple[str, str]] = []
    order_match = re.search(r"\bORDER\s+BY\s+(.*?)(?:\bLIMIT\b|\bOFFSET\b|$)", text, re.I | re.S)
    if order_match:
        for item in order_match.group(1).split(','):
            m = re.match(r"\s*([\w\"]+(?:\.[\w\"]+)?)(?:\s+(ASC|DESC))?", item, re.I)
            if m:
                order_columns.append((*resolve(m.group(1)), (m.group(2) or "ASC").upper()))

    group_columns: list[str] = []
    group_match = re.search(r"\bGROUP\s+BY\s+(.*?)(?:\bORDER\s+BY\b|\bLIMIT\b|\bOFFSET\b|$)", text, re.I | re.S)
    if group_match:
        for item in group_match.group(1).split(','):
            group_columns.append(resolve(item.strip().split()[0])[1])

    select_match = re.match(r"\s*SELECT\s+(.*?)\s+FROM\b", text, re.I | re.S)
    select_star = bool(select_match and "*" in select_match.group(1))
    return QueryShape(relations, aliases, where_columns, join_columns, order_columns, group_columns, select_star)
