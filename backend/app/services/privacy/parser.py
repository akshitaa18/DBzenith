"""Dependency-free PostgreSQL-safe SQL lexer and structural AST."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterator


@dataclass(frozen=True)
class SqlToken:
    kind: str
    value: str


@dataclass
class SqlAst:
    """A lossless structural tree after comments are removed."""

    nodes: list[SqlToken | "SqlAst"] = field(default_factory=list)

    def iter_tokens(self) -> Iterator[SqlToken]:
        for node in self.nodes:
            if isinstance(node, SqlToken):
                yield node
            else:
                yield from node.iter_tokens()


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_NUMBER = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
_PHONE = re.compile(r"^\+?[0-9][0-9() .-]{7,}[0-9]$")
_HEX_KEY = re.compile(r"^(?:sk|pk|ak|api|key|token)[_-]?[A-Za-z0-9_-]{12,}$", re.I)


def _consume_quoted(sql: str, start: int, quote: str) -> tuple[str, int]:
    i = start + 1
    while i < len(sql):
        if sql[i] == quote:
            if i + 1 < len(sql) and sql[i + 1] == quote:
                i += 2
                continue
            return sql[start : i + 1], i + 1
        i += 1
    raise ValueError("unterminated quoted literal/identifier")


def _consume_dollar(sql: str, start: int) -> tuple[str, int] | None:
    m = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", sql[start:])
    if not m:
        return None
    tag = m.group(0)
    end = sql.find(tag, start + len(tag))
    if end < 0:
        raise ValueError("unterminated dollar-quoted literal")
    return sql[start : end + len(tag)], end + len(tag)


def _looks_sensitive_word(value: str) -> bool:
    return bool(_EMAIL.match(value) or _UUID.match(value) or _IPV4.match(value) or _PHONE.match(value) or _HEX_KEY.match(value))


def tokenize_sql(sql: str) -> list[SqlToken]:
    tokens: list[SqlToken] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
            continue
        if sql.startswith("--", i):
            end = sql.find("\n", i + 2)
            i = n if end < 0 else end + 1
            continue
        if sql.startswith("/*", i):
            depth = 1
            i += 2
            while i < n and depth:
                if sql.startswith("/*", i):
                    depth += 1
                    i += 2
                elif sql.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise ValueError("unterminated SQL block comment")
            continue
        if ch in "'\"":
            value, i = _consume_quoted(sql, i, ch)
            tokens.append(SqlToken("STRING" if ch == "'" else "IDENTIFIER", value))
            continue
        dollar = _consume_dollar(sql, i) if ch == "$" else None
        if dollar:
            value, i = dollar
            tokens.append(SqlToken("STRING", value))
            continue
        if ch == ":":
            m = re.match(r":\s*[A-Za-z_][A-Za-z0-9_]*", sql[i:])
            if m:
                tokens.append(SqlToken("PARAM", ":name"))
                i += len(m.group(0))
                continue
            if i + 1 < n and sql[i + 1] == ":":
                tokens.append(SqlToken("OP", "::"))
                i += 2
                continue
        if ch == "$":
            m = re.match(r"\$\d+", sql[i:])
            if m:
                tokens.append(SqlToken("PARAM", "$n"))
                i += len(m.group(0))
                continue
        m = _NUMBER.match(sql, i)
        if m:
            tokens.append(SqlToken("NUMBER", m.group(0)))
            i = m.end()
            continue
        m = _WORD.match(sql, i)
        if m:
            value = m.group(0)
            tokens.append(SqlToken("SENSITIVE" if _looks_sensitive_word(value) else "WORD", value))
            i = m.end()
            continue
        if i + 2 <= n and sql[i : i + 3] in {"->>"}:
            tokens.append(SqlToken("OP", sql[i : i + 3]))
            i += 3
            continue
        if i + 1 < n and sql[i : i + 2] in {"<=", ">=", "<>", "!=", "||", "&&", "->"}:
            tokens.append(SqlToken("OP", sql[i : i + 2]))
            i += 2
            continue
        if ch in ".,;()[]{}+-*/%=<>!~|&^?":
            tokens.append(SqlToken("PUNCT", ch))
            i += 1
            continue
        raise ValueError(f"unsupported SQL character at position {i}")
    return tokens


def build_ast(tokens: list[SqlToken]) -> SqlAst:
    root = SqlAst()
    stack: list[SqlAst] = [root]
    for token in tokens:
        if token.value == "(":
            child = SqlAst()
            stack[-1].nodes.append(child)
            stack.append(child)
        elif token.value == ")":
            if len(stack) == 1:
                raise ValueError("unbalanced closing parenthesis")
            stack.pop()
        else:
            stack[-1].nodes.append(token)
    if len(stack) != 1:
        raise ValueError("unbalanced opening parenthesis")
    return root


def parse_sql(sql: str) -> SqlAst:
    if not sql.strip():
        raise ValueError("SQL must not be empty")
    return build_ast(tokenize_sql(sql))
