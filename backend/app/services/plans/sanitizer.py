from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.services.privacy.contracts import RawPlan, SanitizedPlan
from app.services.privacy.sanitizer import identifier_token

SAFE_KEYS = {
    "Node Type", "Join Type", "Strategy", "Partial Mode", "Parent Relationship", "Parallel Aware",
    "Workers Planned", "Workers Launched", "Startup Cost", "Total Cost", "Plan Rows", "Plan Width",
    "Actual Startup Time", "Actual Total Time", "Actual Rows", "Actual Loops", "Rows Removed by Filter",
    "Rows Removed by Join Filter", "Actual Loops", "Shared Hit Blocks", "Shared Read Blocks",
    "Shared Dirtied Blocks", "Shared Written Blocks", "Local Hit Blocks", "Local Read Blocks",
    "Temp Read Blocks", "Temp Written Blocks", "I/O Read Time", "I/O Write Time", "Plans",
}
EXPRESSION_KEYS = {"Filter", "Index Cond", "Recheck Cond", "Join Filter", "Hash Cond", "Merge Cond", "Sort Key", "Group Key", "Output", "Index Cond"}
IDENTIFIER_KEYS = {"Relation Name", "Schema", "Alias", "Index Name"}

_SECRET = re.compile(r"(?:password|passwd|api[_-]?key|token|secret)\s*[:=]\s*[^\s,)]+", re.I)


def _mask_expression(value: str) -> str:
    value = _SECRET.sub("<SENSITIVE>", value)
    # Reuse the SQL privacy lexer by sanitizing an expression as a predicate.
    try:
        from app.services.privacy.contracts import RawQuery
        from app.services.privacy.sanitizer import sanitize_query
        return sanitize_query(RawQuery(sql=f"SELECT 1 WHERE {value}")).normalized_sql
    except Exception:
        return re.sub(r"'([^']|'')*'", "<STR>", value)


def sanitize_raw_plan(raw: RawPlan) -> SanitizedPlan:
    operators: list[str] = []
    relations: list[str] = []

    def walk(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if k in IDENTIFIER_KEYS:
                    if isinstance(v, str):
                        token = identifier_token(v)
                        relations.append(token)
                        out[k] = token
                    else:
                        out[k] = "<IDENTIFIER>"
                elif k in EXPRESSION_KEYS and isinstance(v, str):
                    out[k] = _mask_expression(v)
                elif k == "Node Type" and isinstance(v, str):
                    operators.append(v)
                    out[k] = v
                elif k in SAFE_KEYS:
                    out[k] = walk(v, k)
                elif k in {"Planning Time", "Execution Time"} and isinstance(v, (int, float)):
                    out[k] = float(v)
                else:
                    # Unknown text/fields are dropped instead of crossing the privacy boundary.
                    if isinstance(v, (dict, list)):
                        out[k] = walk(v, k)
                    elif isinstance(v, (int, float, bool)):
                        out[k] = v
            return out
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, str):
            return value if key in {"Node Type", "Join Type", "Strategy", "Partial Mode", "Parent Relationship"} else "<TEXT>"
        return value

    safe = walk(raw.plan)
    canonical = json.dumps(safe, sort_keys=True, separators=(",", ":"), default=str)
    return SanitizedPlan(plan=safe, structural_hash=hashlib.sha256(canonical.encode()).hexdigest(), operator_types=sorted(set(operators)), relation_tokens=sorted(set(relations)))
