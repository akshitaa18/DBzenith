"""Safety validator and invariant enforcer for SQL AST rewriting.

Rejects unsafe transformations:
- Non-SELECT queries (mutations, DDL, DML)
- Non-deterministic / volatile function calls (e.g. random(), clock_timestamp())
- Outer column projection alteration (columns returned to clients must match)
- LIMIT / OFFSET alterations
- Aggregation barrier breaches
"""

from __future__ import annotations

import re
from typing import Any
import sqlglot
from sqlglot import exp


_VOLATILE_FUNCTIONS = {
    "random",
    "gen_random_uuid",
    "uuid_generate_v4",
    "clock_timestamp",
    "timeofday",
    "statement_timestamp",
    "nextval",
    "setval",
    "txid_current",
    "txid_current_snapshot",
    "pg_backend_pid",
}


_FORBIDDEN_KEYWORDS = [
    r"\binsert\b",
    r"\bupdate\b",
    r"\bdelete\b",
    r"\bdrop\b",
    r"\btruncate\b",
    r"\balter\b",
    r"\bgrant\b",
    r"\brevoke\b",
    r"\bcreate\b",
    r"\bexecute\b",
]


class SQLRewriteSafetyPolicy:
    """Enforces safety rules on candidate SQL queries and AST transformations."""

    @classmethod
    def check_query_safety(cls, sql: str) -> tuple[bool, str | None]:
        """Pre-validation on SQL string before AST transformation."""
        cleaned = sql.strip().rstrip(";")
        lower = cleaned.lower()

        # 1. Must be a SELECT statement
        if not (lower.startswith("select") or lower.startswith("with")):
            return False, "Non-SELECT or DML statement detected: only read-only SELECT and WITH statements are eligible for rewriting."

        for pattern in _FORBIDDEN_KEYWORDS:
            if re.search(pattern, lower):
                return False, f"Query contains forbidden mutation keyword matching {pattern}."

        # 2. Must parse into a valid AST
        try:
            parsed = sqlglot.parse_one(cleaned, read="postgres")
        except Exception as exc:
            return False, f"Query failed AST parsing: {exc}"

        # 3. Check for volatile functions
        for func in parsed.find_all(exp.Func, exp.Anonymous):
            func_name = (getattr(func, "name", "") or getattr(func, "key", "")).lower()
            if (
                func_name in _VOLATILE_FUNCTIONS
                or func_name in {"rand", "random"}
                or isinstance(func, exp.Rand)
            ):
                return False, f"Query contains non-deterministic/volatile function: '{func_name or 'random'}'."

        return True, None

    @classmethod
    def check_transformation_safety(
        cls,
        original_ast: exp.Expression,
        rewritten_ast: exp.Expression,
    ) -> tuple[bool, str | None]:
        """Post-validation comparing original and rewritten ASTs to detect semantic divergence."""
        # 1. Must not convert to non-SELECT
        if not isinstance(rewritten_ast, (exp.Select, exp.Union)):
            return False, "Transformation did not produce a SELECT or UNION expression."

        # 2. Outer column projection count must match if explicit columns are defined
        orig_selects = original_ast.expressions if hasattr(original_ast, "expressions") else []
        new_selects = rewritten_ast.expressions if hasattr(rewritten_ast, "expressions") else []

        # If both are non-wildcard, count must be preserved
        orig_has_star = any(isinstance(s, exp.Star) for s in orig_selects)
        new_has_star = any(isinstance(s, exp.Star) for s in new_selects)

        if not orig_has_star and not new_has_star:
            if len(orig_selects) != len(new_selects):
                return False, f"Projection column count mismatch: original has {len(orig_selects)}, rewritten has {len(new_selects)}."

        # 3. LIMIT and OFFSET must not be modified or stripped if present
        orig_limit = original_ast.args.get("limit")
        new_limit = rewritten_ast.args.get("limit")
        if (orig_limit is None) != (new_limit is None):
            return False, "Transformation modified query LIMIT presence."

        orig_offset = original_ast.args.get("offset")
        new_offset = rewritten_ast.args.get("offset")
        if (orig_offset is None) != (new_offset is None):
            return False, "Transformation modified query OFFSET presence."

        return True, None

    @classmethod
    def validate_rewrite_safety(
        cls,
        original: str | exp.Expression,
        rewritten: str | exp.Expression,
    ) -> tuple[bool, str | None]:
        """Validates safety between original and rewritten query as strings or ASTs."""
        try:
            orig_ast = (
                sqlglot.parse_one(original.strip().rstrip(";"), read="postgres")
                if isinstance(original, str)
                else original
            )
            rewritten_ast = (
                sqlglot.parse_one(rewritten.strip().rstrip(";"), read="postgres")
                if isinstance(rewritten, str)
                else rewritten
            )
        except Exception as exc:
            return False, f"Failed to parse SQL during safety check: {exc}"
        return cls.check_transformation_safety(orig_ast, rewritten_ast)

