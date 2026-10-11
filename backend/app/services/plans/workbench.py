"""Phase 6: PostgreSQL Execution-Plan Comparison and Safe Query Benchmarking Workbench.

Provides:
1. Execution-Plan Diff Engine (`compare_execution_plans`):
   - Side-by-side baseline vs. candidate plan tree normalization.
   - Structural and metric diff across scan types, joins, sorts, estimated rows,
     actual rows, buffer activity, and execution time when available.
   - Missing/added/changed node highlighting and top cost/time contributor attribution.
   - Strict separation between PostgreSQL planner cost units (`planner_cost_units`)
     and measured execution time (`ms`). Never treats planner cost as milliseconds.
   - Graceful handling of absent fields, nested subplans, and divergent plan shapes.

2. Safe Sandbox Benchmarking Runner (`SafeBenchmarkRunner`):
   - Validates SQL syntax and safety (read-only SELECT/WITH, no DML/DDL, no volatile
     or side-effect functions, no multi-statement or comments) before execution.
   - Strictly enforces sandbox-only execution (never executes user SQL on production).
   - Enforces bounded execution time (`statement_timeout`, `lock_timeout`),
     read-only transaction mode (`default_transaction_read_only = on`), resource caps
     (`temp_file_limit`, `max_parallel_workers_per_gather = 0`), concurrency limits,
     and cooperative + backend cancellation (`pg_cancel_backend`).
   - Supports repeatable benchmark runs + configurable warm-up runs, recording median
     (p50), p95, standard deviation, coefficient of variation, buffer hit/read activity,
     and comparability verdicts (`improved`, `regressed`, `inconclusive`, `estimate_only`,
     `unsupported`, `timeout`, `cancelled`, `invalid_sql`, `failed`).
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import statistics
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import sqlglot
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlglot import exp

from app.core.config import get_settings
from app.core.provenance import ProvenanceBadgeLabel, ProvenanceState, badge_for_state
from app.db.session import get_engine, get_sandbox_engine
from app.services.privacy.contracts import RawPlan, RawQuery
from app.services.privacy.gateway import PrivacyGateway
from app.services.privacy.sanitizer import sanitize_query
from app.services.rewriter.safety import SQLRewriteSafetyPolicy


COST_UNIT_LABEL = "planner_cost_units"
COST_DISCLAIMER = (
    "PostgreSQL planner costs are arbitrary relative page/CPU cost units estimated from "
    "catalog statistics. They are NOT milliseconds and must never be interpreted as wall-clock latency."
)

# Scan quality ranking (higher = more selective/index-driven access path)
_SCAN_RANK: dict[str, int] = {
    "Seq Scan": 1,
    "Sample Scan": 1,
    "Foreign Scan": 1,
    "Tid Scan": 2,
    "Subquery Scan": 2,
    "CTE Scan": 2,
    "Function Scan": 2,
    "Values Scan": 2,
    "WorkTable Scan": 2,
    "Bitmap Heap Scan": 3,
    "Bitmap Index Scan": 3,
    "Index Scan": 4,
    "Index Only Scan": 5,
}

_JOIN_TYPES = {"Nested Loop", "Hash Join", "Merge Join"}
_SORT_TYPES = {"Sort", "Incremental Sort"}

# Extended unsafe / side-effect functions that must never be run with EXPLAIN ANALYZE
_UNSAFE_BENCHMARK_FUNCTIONS = {
    "random",
    "gen_random_uuid",
    "uuid_generate_v4",
    "clock_timestamp",
    "timeofday",
    "statement_timestamp",
    "nextval",
    "setval",
    "currval",
    "lastval",
    "txid_current",
    "txid_current_snapshot",
    "pg_current_xact_id",
    "pg_backend_pid",
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",
    "dblink",
    "dblink_exec",
    "dblink_connect",
    "dblink_connect_u",
    "dblink_open",
    "dblink_send_query",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_stat_file",
    "pg_ls_dir",
    "pg_ls_logdir",
    "pg_ls_waldir",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_rotate_logfile",
    "pg_advisory_lock",
    "pg_advisory_xact_lock",
    "pg_try_advisory_lock",
    "pg_advisory_unlock",
    "set_config",
    "lo_import",
    "lo_export",
    "lo_create",
    "lo_unlink",
    "pg_import_system_collations",
    "pg_copy_physical_replication_slot",
    "pg_create_physical_replication_slot",
    "pg_create_logical_replication_slot",
    "pg_drop_replication_slot",
    "pg_switch_wal",
    "pg_create_restore_point",
    "query_to_xml",
    "table_to_xml",
    "cursor_to_xml",
    "database_to_xml",
}

_UNSAFE_SYSTEM_RELATIONS = {
    "pg_authid",
    "pg_shadow",
    "pg_user",
    "pg_roles",
    "pg_stat_activity",
    "pg_settings",
    "pg_file_settings",
    "pg_hba_file_rules",
    "pg_largeobject",
}

_FORBIDDEN_STATEMENT_PATTERNS = [
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
    r"\bprepare\b",
    r"\bdeallocate\b",
    r"\bcopy\b",
    r"\bvacuum\b",
    r"\banalyze\b",
    r"\bcluster\b",
    r"\breindex\b",
    r"\brefresh\b",
    r"\bcall\b",
    r"\bdo\b",
    r"\blisten\b",
    r"\bnotify\b",
    r"\bunlisten\b",
    r"\block\b",
    r"\bdiscard\b",
    r"\bset\s+(?:session|local|transaction|role|time\s+zone|search_path)\b",
    r"\breset\b",
    r"\bfor\s+(?:no\s+key\s+)?update\b",
    r"\bfor\s+(?:key\s+)?share\b",
]

_SAFE_INDEX_DDL_RE = re.compile(
    r"^CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    r"([a-zA-Z_][a-zA-Z0-9_]*)\s+ON\s+(?:([a-zA-Z_][a-zA-Z0-9_]*)\.)?([a-zA-Z_][a-zA-Z0-9_]*)\s*"
    r"(?:USING\s+[a-zA-Z0-9_]+\s*)?\(([^;()]+)\)$",
    re.IGNORECASE,
)

# Concurrency guard and active run cancellation registry for safe benchmarking
_BENCHMARK_SEMAPHORE = threading.BoundedSemaphore(value=2)
_ACTIVE_BENCHMARKS_LOCK = threading.Lock()
_ACTIVE_BENCHMARKS: dict[str, dict[str, Any]] = {}


def scrub_sql_text(sql: str | None) -> str:
    """Scrubs all string, numeric, and sensitive literals from SQL text idempotently."""
    if not sql or not str(sql).strip():
        return ""
    cleaned = str(sql).strip()
    if any(tok in cleaned for tok in ("<STR>", "<NUM>", "<PARAM>", "<SENSITIVE>")) and "'" not in cleaned:
        return re.sub(r"\b\d+(?:\.\d+)?\b", "<NUM>", cleaned)
    try:
        return sanitize_query(RawQuery(sql=cleaned)).normalized_sql
    except Exception:
        # Fallback regex scrubbing if raw expression cannot be tokenized by SQL lexer
        scrubbed = re.sub(r"'([^']|'')*'", "<STR>", cleaned)
        scrubbed = re.sub(r"\b\d+(?:\.\d+)?\b", "<NUM>", scrubbed)
        return scrubbed


def _scrub_condition(cond: Any) -> str | None:
    if cond is None:
        return None
    if isinstance(cond, list):
        parts = [_scrub_condition(item) for item in cond if item is not None]
        return ", ".join(p for p in parts if p)
    text_val = str(cond).strip()
    if not text_val:
        return None
    if any(tok in text_val for tok in ("<STR>", "<NUM>", "<PARAM>", "<SENSITIVE>")) and "'" not in text_val:
        return re.sub(r"\b\d+(?:\.\d+)?\b", "<NUM>", text_val)
    try:
        sanitized = sanitize_query(RawQuery(sql=f"SELECT 1 WHERE {text_val}")).normalized_sql
        prefix = "SELECT <NUM> WHERE "
        if sanitized.startswith(prefix):
            return sanitized[len(prefix) :]
        return sanitized
    except Exception:
        return scrub_sql_text(text_val)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        val = float(value)
        if math.isnan(val) or math.isinf(val):
            return default
        return val
    except (TypeError, ValueError):
        return default


def _safe_optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        val = float(value)
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _extract_root_and_envelope(raw_plan: Any) -> tuple[dict[str, Any] | None, float | None, float | None]:
    """Extracts root Plan dict, Planning Time (ms), and Execution Time (ms) from arbitrary EXPLAIN JSON."""
    if raw_plan is None:
        return None, None, None
    if isinstance(raw_plan, str):
        try:
            raw_plan = json.loads(raw_plan)
        except Exception:
            return None, None, None

    if isinstance(raw_plan, list):
        if not raw_plan:
            return None, None, None
        first = raw_plan[0]
        if isinstance(first, dict):
            planning_ms = _safe_optional_float(first.get("Planning Time"))
            execution_ms = _safe_optional_float(first.get("Execution Time"))
            if isinstance(first.get("Plan"), dict):
                return first["Plan"], planning_ms, execution_ms
            if "Node Type" in first or "Plans" in first or "Total Cost" in first:
                return first, planning_ms, execution_ms
        return None, None, None

    if isinstance(raw_plan, dict):
        planning_ms = _safe_optional_float(raw_plan.get("Planning Time"))
        execution_ms = _safe_optional_float(raw_plan.get("Execution Time"))
        if isinstance(raw_plan.get("Plan"), dict):
            return raw_plan["Plan"], planning_ms, execution_ms
        if "Node Type" in raw_plan or "Plans" in raw_plan or "Total Cost" in raw_plan:
            return raw_plan, planning_ms, execution_ms
        return None, planning_ms, execution_ms

    return None, None, None


@dataclass
class DetailedPlanNode:
    node_id: str
    parent_id: str | None
    depth: int
    structural_path: str
    node_type: str
    parent_relationship: str | None
    relation_name: str | None
    alias: str | None
    index_name: str | None
    join_type: str | None
    strategy: str | None
    sort_key: list[str]
    group_key: list[str]
    filter_condition: str | None
    index_condition: str | None
    join_condition: str | None
    # Planner estimates (NEVER milliseconds!)
    cost_unit: str
    startup_cost: float
    total_cost: float
    exclusive_cost: float
    cost_share_pct: float
    plan_rows: float
    plan_width: int
    # Actual execution measurements (None unless EXPLAIN ANALYZE was run)
    has_actual_timing: bool
    actual_startup_time_ms: float | None
    actual_total_time_ms: float | None
    actual_loops: float | None
    inclusive_actual_time_ms: float | None
    exclusive_actual_time_ms: float | None
    actual_time_share_pct: float | None
    actual_rows: float | None
    rows_removed_by_filter: float | None
    row_estimation_error_ratio: float | None
    row_estimation_q_error: float | None
    # Buffer and I/O metrics
    shared_hit_blocks: int
    shared_read_blocks: int
    shared_dirtied_blocks: int
    shared_written_blocks: int
    temp_read_blocks: int
    temp_written_blocks: int
    io_read_time_ms: float
    io_write_time_ms: float
    buffer_hit_ratio: float | None
    children_ids: list[str] = field(default_factory=list)


@dataclass
class ParsedPlanTree:
    has_plan: bool
    root_id: str | None
    nodes: list[DetailedPlanNode]
    edges: list[dict[str, str]]
    node_count: int
    max_depth: int
    # Planner estimates
    cost_unit: str
    startup_cost: float
    total_cost: float
    estimated_rows: float
    # Actual execution measurements
    has_actual_timing: bool
    planning_time_ms: float | None
    execution_time_ms: float | None
    actual_rows: float | None
    # Aggregated buffers
    total_shared_hit_blocks: int
    total_shared_read_blocks: int
    total_shared_dirtied_blocks: int
    total_shared_written_blocks: int
    total_temp_read_blocks: int
    total_temp_written_blocks: int
    total_io_read_time_ms: float
    total_io_write_time_ms: float
    overall_buffer_hit_ratio: float | None


def parse_plan_tree_detailed(raw_plan: Any) -> ParsedPlanTree:
    """Parses any PostgreSQL EXPLAIN JSON structure into a normalized, safe plan tree."""
    root_dict, planning_ms, envelope_exec_ms = _extract_root_and_envelope(raw_plan)
    if not root_dict:
        return ParsedPlanTree(
            has_plan=False,
            root_id=None,
            nodes=[],
            edges=[],
            node_count=0,
            max_depth=0,
            cost_unit=COST_UNIT_LABEL,
            startup_cost=0.0,
            total_cost=0.0,
            estimated_rows=0.0,
            has_actual_timing=False,
            planning_time_ms=planning_ms,
            execution_time_ms=envelope_exec_ms,
            actual_rows=None,
            total_shared_hit_blocks=0,
            total_shared_read_blocks=0,
            total_shared_dirtied_blocks=0,
            total_shared_written_blocks=0,
            total_temp_read_blocks=0,
            total_temp_written_blocks=0,
            total_io_read_time_ms=0.0,
            total_io_write_time_ms=0.0,
            overall_buffer_hit_ratio=None,
        )

    nodes: list[DetailedPlanNode] = []
    edges: list[dict[str, str]] = []
    node_by_id: dict[str, DetailedPlanNode] = {}

    def _visit(raw_node: dict[str, Any], parent_id: str | None, depth: int, path_prefix: str) -> str:
        node_id = f"n{len(nodes)}"
        node_type = str(raw_node.get("Node Type") or "Unknown")
        relation_name = raw_node.get("Relation Name")
        relation_str = str(relation_name) if isinstance(relation_name, str) and relation_name else None
        alias_raw = raw_node.get("Alias")
        alias_str = str(alias_raw) if isinstance(alias_raw, str) and alias_raw else None
        index_raw = raw_node.get("Index Name")
        index_str = str(index_raw) if isinstance(index_raw, str) and index_raw else None

        path_segment = f"{node_type}:{relation_str or alias_str or index_str or node_id}"
        structural_path = f"{path_prefix}/{path_segment}" if path_prefix else path_segment

        startup_cost = max(0.0, _safe_float(raw_node.get("Startup Cost"), 0.0))
        total_cost = max(0.0, _safe_float(raw_node.get("Total Cost"), 0.0))
        plan_rows = max(0.0, _safe_float(raw_node.get("Plan Rows"), 0.0))
        plan_width = max(0, _safe_int(raw_node.get("Plan Width"), 0))

        actual_startup_ms = _safe_optional_float(raw_node.get("Actual Startup Time"))
        actual_total_ms = _safe_optional_float(raw_node.get("Actual Total Time"))
        actual_loops = _safe_optional_float(raw_node.get("Actual Loops"))
        actual_rows = _safe_optional_float(raw_node.get("Actual Rows"))
        rows_removed = _safe_optional_float(raw_node.get("Rows Removed by Filter"))

        has_actual_timing = actual_total_ms is not None
        loops_factor = max(1.0, actual_loops if actual_loops is not None and actual_loops > 0 else 1.0)
        inclusive_actual_ms = (actual_total_ms * loops_factor) if actual_total_ms is not None else None

        error_ratio: float | None = None
        q_error: float | None = None
        if actual_rows is not None:
            denom = max(1.0, plan_rows)
            actual_safe = max(1.0, actual_rows)
            error_ratio = round(actual_rows / denom, 4)
            q_error = round(max(actual_safe / denom, denom / actual_safe), 4)

        shared_hit = max(0, _safe_int(raw_node.get("Shared Hit Blocks"), 0))
        shared_read = max(0, _safe_int(raw_node.get("Shared Read Blocks"), 0))
        shared_dirtied = max(0, _safe_int(raw_node.get("Shared Dirtied Blocks"), 0))
        shared_written = max(0, _safe_int(raw_node.get("Shared Written Blocks"), 0))
        temp_read = max(0, _safe_int(raw_node.get("Temp Read Blocks"), 0))
        temp_written = max(0, _safe_int(raw_node.get("Temp Written Blocks"), 0))
        io_read_ms = max(0.0, _safe_float(raw_node.get("I/O Read Time"), 0.0))
        io_write_ms = max(0.0, _safe_float(raw_node.get("I/O Write Time"), 0.0))

        total_buf = shared_hit + shared_read
        buf_hit_ratio = round(shared_hit / total_buf, 4) if total_buf > 0 else None

        raw_sort_key = raw_node.get("Sort Key")
        sort_key = (
            [scrub_sql_text(str(k)) for k in raw_sort_key if k is not None]
            if isinstance(raw_sort_key, list)
            else ([scrub_sql_text(str(raw_sort_key))] if raw_sort_key else [])
        )
        raw_group_key = raw_node.get("Group Key")
        group_key = (
            [scrub_sql_text(str(k)) for k in raw_group_key if k is not None]
            if isinstance(raw_group_key, list)
            else ([scrub_sql_text(str(raw_group_key))] if raw_group_key else [])
        )

        filter_cond = _scrub_condition(raw_node.get("Filter") or raw_node.get("Recheck Cond"))
        index_cond = _scrub_condition(raw_node.get("Index Cond") or raw_node.get("TID Cond"))
        join_cond = _scrub_condition(
            raw_node.get("Hash Cond") or raw_node.get("Merge Cond") or raw_node.get("Join Filter")
        )

        node_obj = DetailedPlanNode(
            node_id=node_id,
            parent_id=parent_id,
            depth=depth,
            structural_path=structural_path,
            node_type=node_type,
            parent_relationship=str(raw_node["Parent Relationship"])
            if isinstance(raw_node.get("Parent Relationship"), str)
            else None,
            relation_name=relation_str,
            alias=alias_str,
            index_name=index_str,
            join_type=str(raw_node["Join Type"]) if isinstance(raw_node.get("Join Type"), str) else None,
            strategy=str(raw_node["Strategy"]) if isinstance(raw_node.get("Strategy"), str) else None,
            sort_key=sort_key,
            group_key=group_key,
            filter_condition=filter_cond,
            index_condition=index_cond,
            join_condition=join_cond,
            cost_unit=COST_UNIT_LABEL,
            startup_cost=round(startup_cost, 4),
            total_cost=round(total_cost, 4),
            exclusive_cost=round(total_cost, 4),
            cost_share_pct=0.0,
            plan_rows=round(plan_rows, 2),
            plan_width=plan_width,
            has_actual_timing=has_actual_timing,
            actual_startup_time_ms=round(actual_startup_ms, 4) if actual_startup_ms is not None else None,
            actual_total_time_ms=round(actual_total_ms, 4) if actual_total_ms is not None else None,
            actual_loops=round(actual_loops, 2) if actual_loops is not None else None,
            inclusive_actual_time_ms=round(inclusive_actual_ms, 4) if inclusive_actual_ms is not None else None,
            exclusive_actual_time_ms=round(inclusive_actual_ms, 4) if inclusive_actual_ms is not None else None,
            actual_time_share_pct=None,
            actual_rows=round(actual_rows, 2) if actual_rows is not None else None,
            rows_removed_by_filter=round(rows_removed, 2) if rows_removed is not None else None,
            row_estimation_error_ratio=error_ratio,
            row_estimation_q_error=q_error,
            shared_hit_blocks=shared_hit,
            shared_read_blocks=shared_read,
            shared_dirtied_blocks=shared_dirtied,
            shared_written_blocks=shared_written,
            temp_read_blocks=temp_read,
            temp_written_blocks=temp_written,
            io_read_time_ms=round(io_read_ms, 4),
            io_write_time_ms=round(io_write_ms, 4),
            buffer_hit_ratio=buf_hit_ratio,
            children_ids=[],
        )
        nodes.append(node_obj)
        node_by_id[node_id] = node_obj

        raw_children = raw_node.get("Plans")
        if isinstance(raw_children, list):
            for child_raw in raw_children:
                if isinstance(child_raw, dict):
                    child_id = _visit(child_raw, node_id, depth + 1, structural_path)
                    node_obj.children_ids.append(child_id)
                    edges.append({"from": node_id, "to": child_id})

        return node_id

    root_id = _visit(root_dict, None, 0, "")
    root_node = node_by_id[root_id]

    # Compute exclusive (self) cost and exclusive actual time per node
    for node in nodes:
        children = [node_by_id[cid] for cid in node.children_ids if cid in node_by_id]
        children_cost = sum(c.total_cost for c in children)
        node.exclusive_cost = round(max(0.0, node.total_cost - children_cost), 4)

        if node.inclusive_actual_time_ms is not None:
            children_time = sum(
                c.inclusive_actual_time_ms for c in children if c.inclusive_actual_time_ms is not None
            )
            node.exclusive_actual_time_ms = round(max(0.0, node.inclusive_actual_time_ms - children_time), 4)

    total_exclusive_cost = sum(n.exclusive_cost for n in nodes)
    cost_denom = max(root_node.total_cost, total_exclusive_cost, 1e-9)
    for node in nodes:
        if root_node.total_cost > 0 or total_exclusive_cost > 0:
            node.cost_share_pct = round(min(100.0, (node.exclusive_cost / cost_denom) * 100.0), 2)

    any_actual_timing = any(n.has_actual_timing for n in nodes) or (envelope_exec_ms is not None)
    effective_exec_ms = (
        envelope_exec_ms
        if envelope_exec_ms is not None
        else (root_node.inclusive_actual_time_ms if root_node.has_actual_timing else None)
    )
    total_exclusive_time = sum(n.exclusive_actual_time_ms or 0.0 for n in nodes)
    time_denom = max(effective_exec_ms or 0.0, total_exclusive_time, 1e-9)
    if any_actual_timing and (effective_exec_ms or total_exclusive_time):
        for node in nodes:
            if node.exclusive_actual_time_ms is not None:
                node.actual_time_share_pct = round(
                    min(100.0, (node.exclusive_actual_time_ms / time_denom) * 100.0), 2
                )

    # In PostgreSQL EXPLAIN (BUFFERS), parent nodes accumulate child buffer counts.
    # If root has non-zero buffers, use root's inclusive buffers; otherwise sum leaf/self buffers.
    if root_node.shared_hit_blocks > 0 or root_node.shared_read_blocks > 0:
        tot_hit = root_node.shared_hit_blocks
        tot_read = root_node.shared_read_blocks
        tot_dirtied = root_node.shared_dirtied_blocks
        tot_written = root_node.shared_written_blocks
        tot_temp_r = root_node.temp_read_blocks
        tot_temp_w = root_node.temp_written_blocks
        tot_io_r = root_node.io_read_time_ms
        tot_io_w = root_node.io_write_time_ms
    else:
        tot_hit = sum(n.shared_hit_blocks for n in nodes)
        tot_read = sum(n.shared_read_blocks for n in nodes)
        tot_dirtied = sum(n.shared_dirtied_blocks for n in nodes)
        tot_written = sum(n.shared_written_blocks for n in nodes)
        tot_temp_r = sum(n.temp_read_blocks for n in nodes)
        tot_temp_w = sum(n.temp_written_blocks for n in nodes)
        tot_io_r = round(sum(n.io_read_time_ms for n in nodes), 4)
        tot_io_w = round(sum(n.io_write_time_ms for n in nodes), 4)

    overall_hit_ratio = (
        round(tot_hit / (tot_hit + tot_read), 4) if (tot_hit + tot_read) > 0 else None
    )

    return ParsedPlanTree(
        has_plan=True,
        root_id=root_id,
        nodes=nodes,
        edges=edges,
        node_count=len(nodes),
        max_depth=max((n.depth for n in nodes), default=0),
        cost_unit=COST_UNIT_LABEL,
        startup_cost=root_node.startup_cost,
        total_cost=root_node.total_cost,
        estimated_rows=root_node.plan_rows,
        has_actual_timing=any_actual_timing,
        planning_time_ms=round(planning_ms, 4) if planning_ms is not None else None,
        execution_time_ms=round(effective_exec_ms, 4) if effective_exec_ms is not None else None,
        actual_rows=root_node.actual_rows,
        total_shared_hit_blocks=tot_hit,
        total_shared_read_blocks=tot_read,
        total_shared_dirtied_blocks=tot_dirtied,
        total_shared_written_blocks=tot_written,
        total_temp_read_blocks=tot_temp_r,
        total_temp_written_blocks=tot_temp_w,
        total_io_read_time_ms=tot_io_r,
        total_io_write_time_ms=tot_io_w,
        overall_buffer_hit_ratio=overall_hit_ratio,
    )


def _classify_node_pair(
    base_node: DetailedPlanNode | None,
    cand_node: DetailedPlanNode | None,
) -> tuple[str, str, list[str], str]:
    """Returns (change_type, severity, badges, explanation) for an aligned baseline/candidate node pair."""
    if base_node is not None and cand_node is None:
        if base_node.node_type in _SORT_TYPES:
            return (
                "sort_eliminated",
                "improvement",
                ["SORT ELIMINATED", "REMOVED NODE"],
                (
                    f"Eliminated {base_node.node_type} node (saved {base_node.exclusive_cost:.2f} "
                    f"{COST_UNIT_LABEL})"
                    + (
                        f" and {base_node.exclusive_actual_time_ms:.2f} ms actual sort time."
                        if base_node.exclusive_actual_time_ms is not None
                        else "."
                    )
                ),
            )
        return (
            "removed",
            "info",
            ["REMOVED IN CANDIDATE"],
            f"Baseline {base_node.node_type} ({base_node.relation_name or 'step'}) is no longer present in the candidate plan.",
        )

    if base_node is None and cand_node is not None:
        if cand_node.node_type in _SORT_TYPES:
            return (
                "sort_added",
                "regression",
                ["SORT ADDED", "NEW NODE"],
                (
                    f"Candidate plan introduced an explicit {cand_node.node_type} node "
                    f"(+{cand_node.exclusive_cost:.2f} {COST_UNIT_LABEL})."
                ),
            )
        return (
            "added",
            "info",
            ["ADDED IN CANDIDATE"],
            (
                f"Candidate plan introduced {cand_node.node_type}"
                + (f" using index {cand_node.index_name}" if cand_node.index_name else "")
                + (f" on {cand_node.relation_name}" if cand_node.relation_name else "")
                + f" ({cand_node.exclusive_cost:.2f} {COST_UNIT_LABEL})."
            ),
        )

    assert base_node is not None and cand_node is not None
    badges: list[str] = []
    change_type = "unchanged"
    severity = "neutral"
    notes: list[str] = []

    b_type = base_node.node_type
    c_type = cand_node.node_type
    target_label = cand_node.relation_name or base_node.relation_name or cand_node.alias or base_node.alias or "relation"

    # 1. Scan type transitions
    if b_type in _SCAN_RANK and c_type in _SCAN_RANK and b_type != c_type:
        b_rank = _SCAN_RANK[b_type]
        c_rank = _SCAN_RANK[c_type]
        if c_rank > b_rank:
            change_type = "scan_upgraded"
            severity = "improvement"
            badges.append(f"SCAN UPGRADED: {b_type} -> {c_type}")
            idx_detail = f" via {cand_node.index_name}" if cand_node.index_name else ""
            notes.append(f"Access path on '{target_label}' upgraded from {b_type} to {c_type}{idx_detail}.")
        elif c_rank < b_rank:
            change_type = "scan_degraded"
            severity = "regression"
            badges.append(f"SCAN REGRESSED: {b_type} -> {c_type}")
            notes.append(f"Access path on '{target_label}' regressed from {b_type} to {c_type}.")
        else:
            change_type = "modified"
            badges.append(f"SCAN CHANGED: {b_type} -> {c_type}")
            notes.append(f"Scan operator on '{target_label}' changed from {b_type} to {c_type}.")
    elif b_type in _JOIN_TYPES and c_type in _JOIN_TYPES and b_type != c_type:
        change_type = "join_changed"
        severity = "improvement" if cand_node.total_cost < base_node.total_cost else "modified"
        badges.append(f"JOIN CHANGED: {b_type} -> {c_type}")
        notes.append(f"Join algorithm changed from {b_type} to {c_type}.")
    elif b_type != c_type:
        change_type = "modified"
        badges.append(f"OPERATOR: {b_type} -> {c_type}")
        notes.append(f"Operator changed from {b_type} to {c_type}.")

    # 2. Index change on same scan type
    if base_node.index_name != cand_node.index_name and (base_node.index_name or cand_node.index_name):
        badges.append(f"INDEX: {base_node.index_name or 'none'} -> {cand_node.index_name or 'none'}")
        if change_type == "unchanged":
            change_type = "modified"

    # 3. Cost delta (in planner_cost_units)
    cost_delta = cand_node.total_cost - base_node.total_cost
    cost_rel = abs(cost_delta) / max(base_node.total_cost, 1.0)
    if cost_rel >= 0.05 and abs(cost_delta) >= 0.5:
        if cost_delta < 0:
            badges.append(f"COST {(cost_delta / max(base_node.total_cost, 1e-6)) * 100.0:.1f}%")
            if severity == "neutral":
                severity = "improvement"
            if change_type == "unchanged":
                change_type = "modified"
        else:
            badges.append(f"COST +{(cost_delta / max(base_node.total_cost, 1e-6)) * 100.0:.1f}%")
            if severity == "neutral":
                severity = "regression"
            if change_type == "unchanged":
                change_type = "modified"
        notes.append(
            f"Estimated node cost changed from {base_node.total_cost:.2f} to {cand_node.total_cost:.2f} {COST_UNIT_LABEL}."
        )

    # 4. Estimated rows delta
    row_delta = cand_node.plan_rows - base_node.plan_rows
    if abs(row_delta) >= 10 and (abs(row_delta) / max(base_node.plan_rows, 1.0)) >= 0.1:
        badges.append(f"EST ROWS: {int(base_node.plan_rows)} -> {int(cand_node.plan_rows)}")
        if change_type == "unchanged":
            change_type = "modified"

    # 5. Actual execution time delta (only when both have actual timing!)
    if base_node.inclusive_actual_time_ms is not None and cand_node.inclusive_actual_time_ms is not None:
        time_delta_ms = cand_node.inclusive_actual_time_ms - base_node.inclusive_actual_time_ms
        if abs(time_delta_ms) >= 0.05:
            notes.append(
                f"Measured node execution time changed from {base_node.inclusive_actual_time_ms:.2f} ms "
                f"to {cand_node.inclusive_actual_time_ms:.2f} ms ({time_delta_ms:+.2f} ms)."
            )
            if change_type == "unchanged":
                change_type = "modified"

    # 6. Buffer activity delta
    if base_node.shared_read_blocks != cand_node.shared_read_blocks:
        read_delta = cand_node.shared_read_blocks - base_node.shared_read_blocks
        badges.append(f"DISK READS: {base_node.shared_read_blocks} -> {cand_node.shared_read_blocks}")
        notes.append(f"Shared disk block reads changed by {read_delta:+d} blocks.")
        if change_type == "unchanged":
            change_type = "modified"

    if not notes:
        notes.append(
            f"{c_type} on {target_label} remained structurally unchanged "
            f"({cand_node.total_cost:.2f} {COST_UNIT_LABEL})."
        )

    return change_type, severity, badges, " ".join(notes)


def compare_execution_plans(
    baseline_raw: Any,
    candidate_raw: Any,
    *,
    baseline_sql: str | None = None,
    candidate_sql: str | None = None,
    candidate_index_ddl: str | None = None,
    recommendation_id: int | None = None,
) -> dict[str, Any]:
    """Compares baseline and candidate PostgreSQL execution plans side-by-side.

    Strictly separates estimated planner cost units (`planner_cost_units`) from
    measured execution time (`ms`). Gracefully handles absent fields, nested
    subplans, and divergent plan shapes.
    """
    baseline_tree = parse_plan_tree_detailed(baseline_raw)
    candidate_tree = parse_plan_tree_detailed(candidate_raw)

    matched_base_ids: set[str] = set()
    matched_cand_ids: set[str] = set()
    aligned_pairs: list[tuple[DetailedPlanNode | None, DetailedPlanNode | None]] = []

    # Stage 1: Match scan nodes targeting the same relation/alias in traversal order
    for b_node in baseline_tree.nodes:
        b_rel = b_node.relation_name or b_node.alias
        if not b_rel:
            continue
        for c_node in candidate_tree.nodes:
            if c_node.node_id in matched_cand_ids:
                continue
            c_rel = c_node.relation_name or c_node.alias
            if c_rel == b_rel:
                matched_base_ids.add(b_node.node_id)
                matched_cand_ids.add(c_node.node_id)
                aligned_pairs.append((b_node, c_node))
                break

    # Stage 2: Match structural operators (joins, aggregates, limits, sorts) at similar depth
    for b_node in baseline_tree.nodes:
        if b_node.node_id in matched_base_ids:
            continue
        best_cand: DetailedPlanNode | None = None
        for c_node in candidate_tree.nodes:
            if c_node.node_id in matched_cand_ids:
                continue
            same_category = (
                b_node.node_type == c_node.node_type
                or (b_node.node_type in _JOIN_TYPES and c_node.node_type in _JOIN_TYPES)
                or (b_node.node_type in _SCAN_RANK and c_node.node_type in _SCAN_RANK)
            )
            if same_category:
                best_cand = c_node
                break
        if best_cand is not None:
            matched_base_ids.add(b_node.node_id)
            matched_cand_ids.add(best_cand.node_id)
            aligned_pairs.append((b_node, best_cand))
        else:
            matched_base_ids.add(b_node.node_id)
            aligned_pairs.append((b_node, None))

    # Stage 3: Remaining unmatched candidate nodes (added nodes)
    for c_node in candidate_tree.nodes:
        if c_node.node_id not in matched_cand_ids:
            matched_cand_ids.add(c_node.node_id)
            aligned_pairs.append((None, c_node))

    node_diffs: list[dict[str, Any]] = []
    scan_changes: list[dict[str, Any]] = []
    join_changes: list[dict[str, Any]] = []
    sort_changes: list[dict[str, Any]] = []

    counts = {
        "scan_upgraded": 0,
        "scan_degraded": 0,
        "join_changed": 0,
        "sort_eliminated": 0,
        "sort_added": 0,
        "added": 0,
        "removed": 0,
        "modified": 0,
        "unchanged": 0,
    }

    for idx, (b_node, c_node) in enumerate(aligned_pairs):
        change_type, severity, badges, explanation = _classify_node_pair(b_node, c_node)
        counts[change_type] = counts.get(change_type, 0) + 1

        cost_delta = (
            round((c_node.total_cost if c_node else 0.0) - (b_node.total_cost if b_node else 0.0), 4)
        )
        exclusive_cost_delta = (
            round((c_node.exclusive_cost if c_node else 0.0) - (b_node.exclusive_cost if b_node else 0.0), 4)
        )
        est_rows_delta = (
            round((c_node.plan_rows if c_node else 0.0) - (b_node.plan_rows if b_node else 0.0), 2)
        )

        has_both_actual_time = (
            b_node is not None
            and c_node is not None
            and b_node.inclusive_actual_time_ms is not None
            and c_node.inclusive_actual_time_ms is not None
        )
        actual_time_delta_ms = (
            round(c_node.inclusive_actual_time_ms - b_node.inclusive_actual_time_ms, 4)  # type: ignore[operator]
            if has_both_actual_time
            else None
        )

        diff_entry = {
            "diff_id": f"diff_{idx}",
            "change_type": change_type,
            "severity": severity,
            "badges": badges,
            "explanation": explanation,
            "relation_name": (c_node.relation_name if c_node else None)
            or (b_node.relation_name if b_node else None),
            "baseline_node": asdict(b_node) if b_node is not None else None,
            "candidate_node": asdict(c_node) if c_node is not None else None,
            "metrics_delta": {
                "cost_unit": COST_UNIT_LABEL,
                "total_cost_delta": cost_delta,
                "exclusive_cost_delta": exclusive_cost_delta,
                "estimated_rows_delta": est_rows_delta,
                "actual_time_delta_ms": actual_time_delta_ms,
                "shared_hit_delta_blocks": (
                    (c_node.shared_hit_blocks if c_node else 0) - (b_node.shared_hit_blocks if b_node else 0)
                ),
                "shared_read_delta_blocks": (
                    (c_node.shared_read_blocks if c_node else 0) - (b_node.shared_read_blocks if b_node else 0)
                ),
            },
        }
        node_diffs.append(diff_entry)

        if change_type in {"scan_upgraded", "scan_degraded"} or (
            b_node and c_node and b_node.node_type in _SCAN_RANK and b_node.index_name != c_node.index_name
        ):
            scan_changes.append(
                {
                    "relation": diff_entry["relation_name"],
                    "baseline_scan": b_node.node_type if b_node else None,
                    "candidate_scan": c_node.node_type if c_node else None,
                    "baseline_index": b_node.index_name if b_node else None,
                    "candidate_index": c_node.index_name if c_node else None,
                    "change_type": change_type,
                    "explanation": explanation,
                }
            )
        if change_type == "join_changed":
            join_changes.append(
                {
                    "baseline_join": b_node.node_type if b_node else None,
                    "candidate_join": c_node.node_type if c_node else None,
                    "explanation": explanation,
                }
            )
        if change_type in {"sort_eliminated", "sort_added"}:
            sort_changes.append(
                {
                    "change_type": change_type,
                    "sort_key": (b_node.sort_key if b_node else None) or (c_node.sort_key if c_node else None),
                    "explanation": explanation,
                }
            )

    # Cost contributor attribution (strictly in planner_cost_units)
    def _build_cost_contributors(tree: ParsedPlanTree) -> list[dict[str, Any]]:
        sorted_nodes = sorted(tree.nodes, key=lambda n: n.exclusive_cost, reverse=True)
        out: list[dict[str, Any]] = []
        for rank, n in enumerate(sorted_nodes[:5], start=1):
            target = n.relation_name or n.index_name or n.alias or "intermediate result"
            out.append(
                {
                    "rank": rank,
                    "node_id": n.node_id,
                    "node_type": n.node_type,
                    "target": target,
                    "exclusive_cost": n.exclusive_cost,
                    "inclusive_cost": n.total_cost,
                    "cost_share_pct": n.cost_share_pct,
                    "cost_unit": COST_UNIT_LABEL,
                    "plan_rows": n.plan_rows,
                    "explanation": (
                        f"{n.node_type} on {target} contributes {n.exclusive_cost:.2f} {COST_UNIT_LABEL} "
                        f"({n.cost_share_pct:.1f}% of total estimated plan cost)."
                    ),
                }
            )
        return out

    # Observed execution time contributor attribution (ONLY when actual timing is present)
    def _build_time_contributors(tree: ParsedPlanTree) -> list[dict[str, Any]]:
        if not tree.has_actual_timing:
            return []
        timed_nodes = [n for n in tree.nodes if n.exclusive_actual_time_ms is not None]
        sorted_nodes = sorted(timed_nodes, key=lambda n: n.exclusive_actual_time_ms or 0.0, reverse=True)
        out: list[dict[str, Any]] = []
        for rank, n in enumerate(sorted_nodes[:5], start=1):
            target = n.relation_name or n.index_name or n.alias or "intermediate result"
            out.append(
                {
                    "rank": rank,
                    "node_id": n.node_id,
                    "node_type": n.node_type,
                    "target": target,
                    "exclusive_actual_time_ms": n.exclusive_actual_time_ms,
                    "inclusive_actual_time_ms": n.inclusive_actual_time_ms,
                    "actual_time_share_pct": n.actual_time_share_pct,
                    "actual_rows": n.actual_rows,
                    "plan_rows": n.plan_rows,
                    "row_estimation_q_error": n.row_estimation_q_error,
                    "explanation": (
                        f"{n.node_type} on {target} consumed {n.exclusive_actual_time_ms:.2f} ms "
                        f"({(n.actual_time_share_pct or 0.0):.1f}% of observed execution time)."
                    ),
                }
            )
        return out

    base_total_cost = baseline_tree.total_cost
    cand_total_cost = candidate_tree.total_cost
    cost_delta = round(cand_total_cost - base_total_cost, 4)
    cost_reduction_pct = (
        round(((base_total_cost - cand_total_cost) / base_total_cost) * 100.0, 2)
        if base_total_cost > 0
        else 0.0
    )

    has_both_exec_ms = (
        baseline_tree.execution_time_ms is not None and candidate_tree.execution_time_ms is not None
    )
    exec_delta_ms = (
        round(candidate_tree.execution_time_ms - baseline_tree.execution_time_ms, 4)  # type: ignore[operator]
        if has_both_exec_ms
        else None
    )
    measured_speedup_pct = (
        round(
            ((baseline_tree.execution_time_ms - candidate_tree.execution_time_ms) / baseline_tree.execution_time_ms)  # type: ignore[operator]
            * 100.0,
            2,
        )
        if has_both_exec_ms and (baseline_tree.execution_time_ms or 0.0) > 0
        else None
    )

    shape_changed = (
        baseline_tree.node_count != candidate_tree.node_count
        or counts["added"] > 0
        or counts["removed"] > 0
        or counts["sort_eliminated"] > 0
        or counts["sort_added"] > 0
        or counts["scan_upgraded"] > 0
        or counts["scan_degraded"] > 0
        or counts["join_changed"] > 0
    )

    # Determine plan diff verdict while keeping planner cost separate from measured latency
    if not baseline_tree.has_plan or not candidate_tree.has_plan:
        verdict = "inconclusive"
    elif has_both_exec_ms:
        if (measured_speedup_pct or 0.0) >= 5.0:
            verdict = "improved"
        elif (measured_speedup_pct or 0.0) <= -5.0:
            verdict = "regressed"
        elif cost_reduction_pct >= 5.0:
            verdict = "improved"
        elif cost_reduction_pct <= -5.0:
            verdict = "regressed"
        else:
            verdict = "unchanged"
    else:
        if cost_reduction_pct >= 5.0 or counts["scan_upgraded"] > 0 or counts["sort_eliminated"] > 0:
            verdict = "estimate_only_improved"
        elif cost_reduction_pct <= -5.0 or counts["scan_degraded"] > 0 or counts["sort_added"] > 0:
            verdict = "estimate_only_regressed"
        else:
            verdict = "unchanged"

    narrative_parts: list[str] = []
    if not baseline_tree.has_plan or not candidate_tree.has_plan:
        narrative_parts.append(
            "One or both execution plans had missing or empty plan structures; partial comparison shown safely."
        )
    else:
        narrative_parts.append(
            f"Planner estimated total cost changed from {base_total_cost:.2f} to {cand_total_cost:.2f} "
            f"{COST_UNIT_LABEL} ({cost_reduction_pct:+.2f}% reduction; note: {COST_UNIT_LABEL} are not milliseconds)."
        )
        if has_both_exec_ms:
            narrative_parts.append(
                f"Observed execution time changed from {baseline_tree.execution_time_ms:.2f} ms to "
                f"{candidate_tree.execution_time_ms:.2f} ms ({measured_speedup_pct:+.2f}% speedup)."
            )
        else:
            narrative_parts.append(
                "No EXPLAIN ANALYZE timing was present on both plans; comparison reflects planner cost estimates only."
            )
        if scan_changes:
            narrative_parts.append(scan_changes[0]["explanation"])
        if sort_changes:
            narrative_parts.append(sort_changes[0]["explanation"])
        if join_changes:
            narrative_parts.append(join_changes[0]["explanation"])

    sanitized_baseline_sql = scrub_sql_text(baseline_sql) if baseline_sql else None
    sanitized_candidate_sql = scrub_sql_text(candidate_sql) if candidate_sql else sanitized_baseline_sql

    return {
        "verdict": verdict,
        "narrative_explanation": " ".join(narrative_parts),
        "cost_unit": COST_UNIT_LABEL,
        "cost_disclaimer": COST_DISCLAIMER,
        "has_actual_timing": has_both_exec_ms,
        "candidate_change_context": {
            "sanitized_baseline_sql": sanitized_baseline_sql,
            "sanitized_candidate_sql": sanitized_candidate_sql,
            "candidate_index_ddl": candidate_index_ddl,
            "recommendation_id": recommendation_id,
        },
        "cost_comparison": {
            "unit": COST_UNIT_LABEL,
            "is_measured_latency": False,
            "baseline_startup_cost": baseline_tree.startup_cost,
            "baseline_total_cost": base_total_cost,
            "candidate_startup_cost": candidate_tree.startup_cost,
            "candidate_total_cost": cand_total_cost,
            "cost_delta": cost_delta,
            "cost_reduction_pct": cost_reduction_pct,
            "baseline_estimated_rows": baseline_tree.estimated_rows,
            "candidate_estimated_rows": candidate_tree.estimated_rows,
            "disclaimer": COST_DISCLAIMER,
        },
        "actual_execution_comparison": {
            "unit": "ms",
            "is_measured_latency": has_both_exec_ms,
            "has_baseline_actuals": baseline_tree.has_actual_timing,
            "has_candidate_actuals": candidate_tree.has_actual_timing,
            "baseline_planning_time_ms": baseline_tree.planning_time_ms,
            "candidate_planning_time_ms": candidate_tree.planning_time_ms,
            "baseline_execution_time_ms": baseline_tree.execution_time_ms,
            "candidate_execution_time_ms": candidate_tree.execution_time_ms,
            "execution_time_delta_ms": exec_delta_ms,
            "measured_speedup_pct": measured_speedup_pct,
            "baseline_actual_rows": baseline_tree.actual_rows,
            "candidate_actual_rows": candidate_tree.actual_rows,
        },
        "buffer_comparison": {
            "baseline_shared_hit_blocks": baseline_tree.total_shared_hit_blocks,
            "candidate_shared_hit_blocks": candidate_tree.total_shared_hit_blocks,
            "shared_hit_delta_blocks": (
                candidate_tree.total_shared_hit_blocks - baseline_tree.total_shared_hit_blocks
            ),
            "baseline_shared_read_blocks": baseline_tree.total_shared_read_blocks,
            "candidate_shared_read_blocks": candidate_tree.total_shared_read_blocks,
            "shared_read_delta_blocks": (
                candidate_tree.total_shared_read_blocks - baseline_tree.total_shared_read_blocks
            ),
            "baseline_temp_written_blocks": baseline_tree.total_temp_written_blocks,
            "candidate_temp_written_blocks": candidate_tree.total_temp_written_blocks,
            "baseline_buffer_hit_ratio": baseline_tree.overall_buffer_hit_ratio,
            "candidate_buffer_hit_ratio": candidate_tree.overall_buffer_hit_ratio,
        },
        "structural_changes_summary": {
            "shape_changed": shape_changed,
            "baseline_node_count": baseline_tree.node_count,
            "candidate_node_count": candidate_tree.node_count,
            "baseline_max_depth": baseline_tree.max_depth,
            "candidate_max_depth": candidate_tree.max_depth,
            "counts": counts,
            "scan_changes": scan_changes,
            "join_changes": join_changes,
            "sort_changes": sort_changes,
        },
        "cost_contributors": {
            "unit": COST_UNIT_LABEL,
            "baseline": _build_cost_contributors(baseline_tree),
            "candidate": _build_cost_contributors(candidate_tree),
        },
        "time_contributors": {
            "unit": "ms",
            "available": baseline_tree.has_actual_timing or candidate_tree.has_actual_timing,
            "baseline": _build_time_contributors(baseline_tree),
            "candidate": _build_time_contributors(candidate_tree),
        },
        "baseline_plan": asdict(baseline_tree),
        "candidate_plan": asdict(candidate_tree),
        "node_diffs": node_diffs,
    }


@dataclass
class SQLSafetyValidationResult:
    status: str  # "safe" | "invalid_sql" | "unsupported"
    is_safe: bool
    explain_analyze_allowed: bool
    reason: str | None
    cleaned_sql: str
    sanitized_sql: str
    synthesized_parameters_count: int = 0


def validate_and_prepare_benchmark_sql(
    sql: str | None,
    parameters: dict[str, Any] | list[Any] | None = None,
) -> SQLSafetyValidationResult:
    """Validates SQL syntax and safety for sandbox benchmarking and EXPLAIN ANALYZE.

    Never allows multi-statement queries, comments, DML/DDL, locking clauses,
    volatile/side-effect functions, or sensitive system catalog queries.
    Safely synthesizes query parameters without exposing raw parameter values.
    """
    if not sql or not str(sql).strip():
        return SQLSafetyValidationResult(
            status="invalid_sql",
            is_safe=False,
            explain_analyze_allowed=False,
            reason="Empty SQL query cannot be parsed or benchmarked.",
            cleaned_sql="",
            sanitized_sql="",
        )

    raw_text = str(sql).strip()
    if raw_text.endswith(";"):
        raw_text = raw_text[:-1].strip()

    sanitized_repr = scrub_sql_text(raw_text)

    # Reject multi-statement or embedded comments
    if ";" in raw_text:
        return SQLSafetyValidationResult(
            status="unsupported",
            is_safe=False,
            explain_analyze_allowed=False,
            reason="Multi-statement SQL strings (containing ';') are not permitted in the benchmark workbench.",
            cleaned_sql=raw_text,
            sanitized_sql=sanitized_repr,
        )
    if "--" in raw_text or "/*" in raw_text or "*/" in raw_text:
        return SQLSafetyValidationResult(
            status="unsupported",
            is_safe=False,
            explain_analyze_allowed=False,
            reason="SQL comments are not permitted in benchmark queries.",
            cleaned_sql=raw_text,
            sanitized_sql=sanitized_repr,
        )

    lower = raw_text.lower()
    if not (lower.startswith("select") or lower.startswith("with")):
        return SQLSafetyValidationResult(
            status="unsupported",
            is_safe=False,
            explain_analyze_allowed=False,
            reason="Only read-only SELECT and WITH queries are supported for benchmarking; DML and DDL are rejected.",
            cleaned_sql=raw_text,
            sanitized_sql=sanitized_repr,
        )

    for pattern in _FORBIDDEN_STATEMENT_PATTERNS:
        if re.search(pattern, lower):
            return SQLSafetyValidationResult(
                status="unsupported",
                is_safe=False,
                explain_analyze_allowed=False,
                reason=f"Statement contains unsafe or side-effect keyword matching '{pattern}'. EXPLAIN ANALYZE refused.",
                cleaned_sql=raw_text,
                sanitized_sql=sanitized_repr,
            )

    # Synthesize positional ($1, $2) or named (:param) placeholders safely so AST parsing and sandbox execution succeed
    synth_count = 0

    def _replace_positional(match: re.Match[str]) -> str:
        nonlocal synth_count
        synth_count += 1
        idx = int(match.group(1)) - 1
        if isinstance(parameters, list) and 0 <= idx < len(parameters):
            val = parameters[idx]
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return str(val)
        return "1"

    prepared_sql = re.sub(r"\$(\d+)\b", _replace_positional, raw_text)

    # Parse with sqlglot to verify grammatical validity and inspect AST nodes
    try:
        statements = sqlglot.parse(prepared_sql, read="postgres")
    except Exception as exc:
        return SQLSafetyValidationResult(
            status="invalid_sql",
            is_safe=False,
            explain_analyze_allowed=False,
            reason=f"SQL syntax parsing failed: {exc}",
            cleaned_sql=raw_text,
            sanitized_sql=sanitized_repr,
        )

    if not statements or len(statements) != 1 or statements[0] is None:
        return SQLSafetyValidationResult(
            status="invalid_sql",
            is_safe=False,
            explain_analyze_allowed=False,
            reason="SQL did not parse into a single valid SELECT expression.",
            cleaned_sql=raw_text,
            sanitized_sql=sanitized_repr,
        )

    ast = statements[0]
    if not isinstance(ast, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        return SQLSafetyValidationResult(
            status="unsupported",
            is_safe=False,
            explain_analyze_allowed=False,
            reason=f"Unsupported root AST expression '{type(ast).__name__}'; only SELECT queries are supported.",
            cleaned_sql=raw_text,
            sanitized_sql=sanitized_repr,
        )

    # Check for forbidden AST mutation nodes inside CTEs or subqueries
    forbidden_ast_types = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Create,
        exp.Drop,
        exp.Alter,
        exp.Command,
        exp.Transaction,
        exp.Commit,
        exp.Rollback,
    )
    for bad_node in ast.find_all(*forbidden_ast_types):
        return SQLSafetyValidationResult(
            status="unsupported",
            is_safe=False,
            explain_analyze_allowed=False,
            reason=f"Query contains unsafe AST node '{type(bad_node).__name__}'.",
            cleaned_sql=raw_text,
            sanitized_sql=sanitized_repr,
        )

    # Check for locking clauses (FOR UPDATE / FOR SHARE)
    if ast.find(exp.Lock):
        return SQLSafetyValidationResult(
            status="unsupported",
            is_safe=False,
            explain_analyze_allowed=False,
            reason="Row-locking clauses (FOR UPDATE / FOR SHARE) have lock side effects and cannot be benchmarked.",
            cleaned_sql=raw_text,
            sanitized_sql=sanitized_repr,
        )

    # Check for volatile or side-effect functions
    for func in ast.find_all(exp.Func, exp.Anonymous):
        func_name = (getattr(func, "name", "") or getattr(func, "key", "")).lower()
        if (
            func_name in _UNSAFE_BENCHMARK_FUNCTIONS
            or func_name in {"rand", "random"}
            or isinstance(func, exp.Rand)
        ):
            return SQLSafetyValidationResult(
                status="unsupported",
                is_safe=False,
                explain_analyze_allowed=False,
                reason=(
                    f"Query invokes volatile or side-effect function '{func_name or 'random'}'. "
                    "EXPLAIN ANALYZE is blocked on statements with side effects or non-deterministic functions."
                ),
                cleaned_sql=raw_text,
                sanitized_sql=sanitized_repr,
            )

    # Check for sensitive system catalogs
    for tbl in ast.find_all(exp.Table):
        tbl_name = (tbl.name or "").lower()
        if tbl_name in _UNSAFE_SYSTEM_RELATIONS:
            return SQLSafetyValidationResult(
                status="unsupported",
                is_safe=False,
                explain_analyze_allowed=False,
                reason=f"System relation '{tbl_name}' is not eligible for sandbox benchmarking.",
                cleaned_sql=raw_text,
                sanitized_sql=sanitized_repr,
            )

    return SQLSafetyValidationResult(
        status="safe",
        is_safe=True,
        explain_analyze_allowed=True,
        reason=None,
        cleaned_sql=prepared_sql,
        sanitized_sql=scrub_sql_text(prepared_sql),
        synthesized_parameters_count=synth_count,
    )


def validate_candidate_index_ddl(index_ddl: str | None) -> tuple[bool, str | None, str | None]:
    """Validates that a candidate index definition is a single safe CREATE INDEX statement."""
    if not index_ddl or not str(index_ddl).strip():
        return True, None, None
    cleaned = str(index_ddl).strip().rstrip(";").strip()
    if ";" in cleaned or "--" in cleaned or "/*" in cleaned:
        return False, "Candidate index DDL must not contain multiple statements or comments.", None
    match = _SAFE_INDEX_DDL_RE.match(cleaned)
    if not match:
        return (
            False,
            "Candidate index DDL must match 'CREATE [UNIQUE] INDEX <name> ON <table> (<columns>)'.",
            None,
        )
    idx_name, _schema, tbl_name, cols = match.groups()
    safe_ddl = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {tbl_name} ({cols.strip()})"
    return True, None, safe_ddl


def _compute_percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return sorted_vals[low]
    weight = rank - low
    return sorted_vals[low] * (1.0 - weight) + sorted_vals[high] * weight


def summarize_benchmark_samples(
    samples_ms: list[float],
    warmup_samples_ms: list[float],
    shared_hits: list[int],
    shared_reads: list[int],
    actual_rows_list: list[float],
    failed_runs: int,
    warmup_runs_requested: int,
    measured_runs_requested: int,
) -> dict[str, Any]:
    """Computes p50 (median), p95, mean, stddev, CV, and cache metrics for a benchmark series."""
    n = len(samples_ms)
    if n == 0:
        return {
            "unit": "ms",
            "is_measured": False,
            "warmup_runs_requested": warmup_runs_requested,
            "warmup_runs_completed": len(warmup_samples_ms),
            "measured_runs_requested": measured_runs_requested,
            "sample_count": 0,
            "failed_runs": failed_runs,
            "samples_ms": [],
            "cold_first_run_ms": round(warmup_samples_ms[0], 4) if warmup_samples_ms else None,
            "median_ms": None,
            "p95_ms": None,
            "p95_note": "No measured samples available.",
            "mean_ms": None,
            "min_ms": None,
            "max_ms": None,
            "stddev_ms": None,
            "coefficient_of_variation": None,
            "shared_hit_blocks_median": 0,
            "shared_read_blocks_median": 0,
            "cache_hit_ratio": None,
            "cache_state": "unmeasured",
            "actual_rows": None,
        }

    ordered = sorted(samples_ms)
    median_val = statistics.median(ordered)
    mean_val = statistics.mean(ordered)
    min_val = ordered[0]
    max_val = ordered[-1]
    stddev_val = statistics.stdev(ordered) if n >= 2 else 0.0
    cv_val = (stddev_val / mean_val) if mean_val > 0 else 0.0
    p95_val = _compute_percentile(ordered, 95.0)
    p95_note = (
        f"Computed across {n} measured runs."
        if n >= 3
        else f"Interpolated from {n} sample(s); >=3 runs recommended for stable p95."
    )

    med_hits = int(statistics.median(shared_hits)) if shared_hits else 0
    med_reads = int(statistics.median(shared_reads)) if shared_reads else 0
    tot_blk = med_hits + med_reads
    hit_ratio = round(med_hits / tot_blk, 4) if tot_blk > 0 else None

    if len(warmup_samples_ms) >= 1 and med_reads == 0 and med_hits > 0:
        cache_state = "warm_buffer_cache"
    elif med_reads > 0:
        cache_state = "mixed_or_disk_reads_observed"
    else:
        cache_state = "warmed" if len(warmup_samples_ms) >= 1 else "cold_unwarmed"

    return {
        "unit": "ms",
        "is_measured": True,
        "warmup_runs_requested": warmup_runs_requested,
        "warmup_runs_completed": len(warmup_samples_ms),
        "measured_runs_requested": measured_runs_requested,
        "sample_count": n,
        "failed_runs": failed_runs,
        "samples_ms": [round(x, 4) for x in samples_ms],
        "cold_first_run_ms": round(warmup_samples_ms[0], 4)
        if warmup_samples_ms
        else round(samples_ms[0], 4),
        "median_ms": round(median_val, 4),
        "p95_ms": round(p95_val, 4),
        "p95_note": p95_note,
        "mean_ms": round(mean_val, 4),
        "min_ms": round(min_val, 4),
        "max_ms": round(max_val, 4),
        "stddev_ms": round(stddev_val, 4),
        "coefficient_of_variation": round(cv_val, 4),
        "shared_hit_blocks_median": med_hits,
        "shared_read_blocks_median": med_reads,
        "cache_hit_ratio": hit_ratio,
        "cache_state": cache_state,
        "actual_rows": round(actual_rows_list[-1], 2) if actual_rows_list else None,
    }


def cancel_benchmark_run(run_id: str, sandbox_engine: Engine | None = None) -> dict[str, Any]:
    """Signals cooperative cancellation for an active benchmark run and cancels its sandbox PID if active."""
    with _ACTIVE_BENCHMARKS_LOCK:
        entry = _ACTIVE_BENCHMARKS.get(run_id)
        if entry is None:
            return {
                "run_id": run_id,
                "status": "not_found_or_already_completed",
                "cancelled": False,
                "message": "Benchmark run is not currently active or has already finished.",
            }
        entry["cancelled"] = True
        pid = entry.get("backend_pid")

    pg_cancelled = False
    if pid is not None:
        try:
            eng = sandbox_engine or get_sandbox_engine()
            with eng.connect() as conn:
                pg_cancelled = bool(
                    conn.execute(text("SELECT pg_cancel_backend(:pid)"), {"pid": int(pid)}).scalar()
                )
        except Exception:
            pg_cancelled = False

    return {
        "run_id": run_id,
        "status": "cancelled",
        "cancelled": True,
        "pg_cancel_backend_sent": pg_cancelled,
        "message": "Cancellation requested for sandbox benchmark run.",
    }


class SafeBenchmarkRunner:
    """Executes bounded, isolated query benchmarks against the sandbox database ONLY."""

    def __init__(self, sandbox_engine: Engine | None = None) -> None:
        self._injected_sandbox_engine = sandbox_engine
        self.privacy_gateway = PrivacyGateway()

    def _resolve_sandbox_engine(self) -> Engine:
        eng = self._injected_sandbox_engine or get_sandbox_engine()
        self._assert_not_production_engine(eng)
        return eng

    @staticmethod
    def _assert_not_production_engine(candidate_engine: Any) -> None:
        """Hard guard ensuring production engine/session is NEVER used by the sandbox benchmark path."""
        if isinstance(candidate_engine, Session):
            raise RuntimeError(
                "SECURITY VIOLATION: SafeBenchmarkRunner received a database Session instead of the isolated sandbox Engine."
            )
        try:
            prod_engine = get_engine()
        except Exception:
            prod_engine = None

        if prod_engine is not None and candidate_engine is prod_engine:
            raise RuntimeError(
                "SECURITY VIOLATION: SafeBenchmarkRunner refused to execute against the production database engine."
            )

        settings = get_settings()
        cand_url = str(getattr(candidate_engine, "url", ""))
        if (
            cand_url
            and settings.database_url != settings.sandbox_database_url
            and cand_url == settings.database_url
        ):
            raise RuntimeError(
                "SECURITY VIOLATION: Sandbox engine URL matches production database_url while a distinct sandbox_database_url is configured."
            )

    def run_benchmark(
        self,
        *,
        baseline_sql: str,
        candidate_sql: str | None = None,
        candidate_index_ddl: str | None = None,
        baseline_plan_raw: Any = None,
        candidate_plan_raw: Any = None,
        parameters: dict[str, Any] | list[Any] | None = None,
        warmup_runs: int = 1,
        benchmark_runs: int = 3,
        statement_timeout_ms: int = 3000,
        run_id: str | None = None,
        pre_cancelled: bool = False,
        recommendation_id: int | None = None,
    ) -> dict[str, Any]:
        """Runs a safe, bounded comparison and benchmark between baseline and candidate in the sandbox."""
        effective_run_id = run_id or f"bench-{uuid.uuid4().hex[:12]}"
        warmup_runs = max(0, min(int(warmup_runs), 5))
        benchmark_runs = max(1, min(int(benchmark_runs), 10))
        statement_timeout_ms = max(50, min(int(statement_timeout_ms), 15000))

        # 1. Validate baseline SQL safety and syntax BEFORE any DB connection
        base_validation = validate_and_prepare_benchmark_sql(baseline_sql, parameters=parameters)
        if not base_validation.is_safe:
            return self._build_non_executed_response(
                run_id=effective_run_id,
                status=base_validation.status,
                reason=base_validation.reason or "Baseline query failed safety validation.",
                sanitized_baseline_sql=base_validation.sanitized_sql,
                sanitized_candidate_sql=scrub_sql_text(candidate_sql) if candidate_sql else base_validation.sanitized_sql,
                candidate_index_ddl=candidate_index_ddl,
                warmup_runs=warmup_runs,
                benchmark_runs=benchmark_runs,
                statement_timeout_ms=statement_timeout_ms,
                recommendation_id=recommendation_id,
            )

        # 2. Validate candidate SQL if provided
        effective_candidate_sql = candidate_sql.strip() if candidate_sql and candidate_sql.strip() else baseline_sql
        cand_validation = validate_and_prepare_benchmark_sql(effective_candidate_sql, parameters=parameters)
        if not cand_validation.is_safe:
            return self._build_non_executed_response(
                run_id=effective_run_id,
                status=cand_validation.status,
                reason=f"Candidate SQL rejected: {cand_validation.reason}",
                sanitized_baseline_sql=base_validation.sanitized_sql,
                sanitized_candidate_sql=cand_validation.sanitized_sql,
                candidate_index_ddl=candidate_index_ddl,
                warmup_runs=warmup_runs,
                benchmark_runs=benchmark_runs,
                statement_timeout_ms=statement_timeout_ms,
                recommendation_id=recommendation_id,
            )

        # 3. Validate candidate index DDL if provided
        ddl_ok, ddl_reason, safe_index_ddl = validate_candidate_index_ddl(candidate_index_ddl)
        if not ddl_ok:
            return self._build_non_executed_response(
                run_id=effective_run_id,
                status="unsupported",
                reason=ddl_reason or "Candidate index DDL failed safety validation.",
                sanitized_baseline_sql=base_validation.sanitized_sql,
                sanitized_candidate_sql=cand_validation.sanitized_sql,
                candidate_index_ddl=candidate_index_ddl,
                warmup_runs=warmup_runs,
                benchmark_runs=benchmark_runs,
                statement_timeout_ms=statement_timeout_ms,
                recommendation_id=recommendation_id,
            )

        # 4. Check immediate cancellation
        if pre_cancelled:
            return self._build_non_executed_response(
                run_id=effective_run_id,
                status="cancelled",
                reason="Benchmark run was cancelled before execution started.",
                sanitized_baseline_sql=base_validation.sanitized_sql,
                sanitized_candidate_sql=cand_validation.sanitized_sql,
                candidate_index_ddl=safe_index_ddl,
                warmup_runs=warmup_runs,
                benchmark_runs=benchmark_runs,
                statement_timeout_ms=statement_timeout_ms,
                recommendation_id=recommendation_id,
            )

        # 5. Acquire concurrency slot
        acquired = _BENCHMARK_SEMAPHORE.acquire(timeout=2.0)
        if not acquired:
            return self._build_non_executed_response(
                run_id=effective_run_id,
                status="busy",
                reason="Maximum concurrent sandbox benchmarks reached. Please retry shortly.",
                sanitized_baseline_sql=base_validation.sanitized_sql,
                sanitized_candidate_sql=cand_validation.sanitized_sql,
                candidate_index_ddl=safe_index_ddl,
                warmup_runs=warmup_runs,
                benchmark_runs=benchmark_runs,
                statement_timeout_ms=statement_timeout_ms,
                recommendation_id=recommendation_id,
            )

        with _ACTIVE_BENCHMARKS_LOCK:
            existing_cancelled = bool(_ACTIVE_BENCHMARKS.get(effective_run_id, {}).get("cancelled"))
            _ACTIVE_BENCHMARKS[effective_run_id] = {
                "run_id": effective_run_id,
                "started_at": time.time(),
                "cancelled": existing_cancelled,
                "backend_pid": None,
            }

        try:
            if existing_cancelled:
                return self._build_non_executed_response(
                    run_id=effective_run_id,
                    status="cancelled",
                    reason="Benchmark run was cancelled before sandbox execution.",
                    sanitized_baseline_sql=base_validation.sanitized_sql,
                    sanitized_candidate_sql=cand_validation.sanitized_sql,
                    candidate_index_ddl=safe_index_ddl,
                    warmup_runs=warmup_runs,
                    benchmark_runs=benchmark_runs,
                    statement_timeout_ms=statement_timeout_ms,
                    recommendation_id=recommendation_id,
                )

            return self._execute_in_sandbox(
                run_id=effective_run_id,
                base_validation=base_validation,
                cand_validation=cand_validation,
                safe_index_ddl=safe_index_ddl,
                fallback_baseline_plan=baseline_plan_raw,
                fallback_candidate_plan=candidate_plan_raw,
                warmup_runs=warmup_runs,
                benchmark_runs=benchmark_runs,
                statement_timeout_ms=statement_timeout_ms,
                recommendation_id=recommendation_id,
            )
        finally:
            with _ACTIVE_BENCHMARKS_LOCK:
                _ACTIVE_BENCHMARKS.pop(effective_run_id, None)
            _BENCHMARK_SEMAPHORE.release()

    @staticmethod
    def _is_run_cancelled(run_id: str) -> bool:
        with _ACTIVE_BENCHMARKS_LOCK:
            return bool(_ACTIVE_BENCHMARKS.get(run_id, {}).get("cancelled"))

    def _execute_in_sandbox(
        self,
        *,
        run_id: str,
        base_validation: SQLSafetyValidationResult,
        cand_validation: SQLSafetyValidationResult,
        safe_index_ddl: str | None,
        fallback_baseline_plan: Any,
        fallback_candidate_plan: Any,
        warmup_runs: int,
        benchmark_runs: int,
        statement_timeout_ms: int,
        recommendation_id: int | None,
    ) -> dict[str, Any]:
        sandbox_engine = self._resolve_sandbox_engine()
        settings = get_settings()

        base_warmup_ms: list[float] = []
        base_samples_ms: list[float] = []
        base_hits: list[int] = []
        base_reads: list[int] = []
        base_rows: list[float] = []
        base_failed = 0
        captured_base_plan: Any = None

        cand_warmup_ms: list[float] = []
        cand_samples_ms: list[float] = []
        cand_hits: list[int] = []
        cand_reads: list[int] = []
        cand_rows: list[float] = []
        cand_failed = 0
        captured_cand_plan: Any = None

        timeout_occurred = False
        cancelled_occurred = False
        unsupported_reason: str | None = None
        execution_error: str | None = None

        try:
            with sandbox_engine.connect() as conn:
                try:
                    pid = conn.execute(text("SELECT pg_backend_pid()")).scalar()
                    with _ACTIVE_BENCHMARKS_LOCK:
                        if run_id in _ACTIVE_BENCHMARKS:
                            _ACTIVE_BENCHMARKS[run_id]["backend_pid"] = pid
                except Exception:
                    pass

                # Apply strict session resource safeguards
                self._apply_session_safeguards(conn, statement_timeout_ms=statement_timeout_ms, read_only=True)

                # --- Phase 1: Baseline warm-up & measured runs ---
                total_base_iters = warmup_runs + benchmark_runs
                for i in range(total_base_iters):
                    if self._is_run_cancelled(run_id):
                        cancelled_occurred = True
                        break
                    plan_json, exec_ms, hits, reads, rows_val = self._run_single_explain_analyze(
                        conn, base_validation.cleaned_sql
                    )
                    if captured_base_plan is None and plan_json is not None:
                        captured_base_plan = plan_json
                    if i < warmup_runs:
                        if exec_ms is not None:
                            base_warmup_ms.append(exec_ms)
                    else:
                        if exec_ms is not None:
                            base_samples_ms.append(exec_ms)
                            base_hits.append(hits)
                            base_reads.append(reads)
                            if rows_val is not None:
                                base_rows.append(rows_val)
                        else:
                            base_failed += 1

                conn.rollback()

                # --- Phase 2: Candidate warm-up & measured runs (inside rolled-back transaction if index DDL) ---
                if not cancelled_occurred:
                    if safe_index_ddl:
                        # Temporarily allow DDL inside uncommitted sandbox transaction, then lock read-only for query
                        self._apply_session_safeguards(
                            conn, statement_timeout_ms=statement_timeout_ms, read_only=False
                        )
                        conn.execute(text("SET LOCAL enable_seqscan = off"))
                        conn.execute(text(safe_index_ddl))
                        self._apply_session_safeguards(
                            conn, statement_timeout_ms=statement_timeout_ms, read_only=True
                        )
                    else:
                        self._apply_session_safeguards(
                            conn, statement_timeout_ms=statement_timeout_ms, read_only=True
                        )

                    total_cand_iters = warmup_runs + benchmark_runs
                    for i in range(total_cand_iters):
                        if self._is_run_cancelled(run_id):
                            cancelled_occurred = True
                            break
                        plan_json, exec_ms, hits, reads, rows_val = self._run_single_explain_analyze(
                            conn, cand_validation.cleaned_sql
                        )
                        if captured_cand_plan is None and plan_json is not None:
                            captured_cand_plan = plan_json
                        if i < warmup_runs:
                            if exec_ms is not None:
                                cand_warmup_ms.append(exec_ms)
                        else:
                            if exec_ms is not None:
                                cand_samples_ms.append(exec_ms)
                                cand_hits.append(hits)
                                cand_reads.append(reads)
                                if rows_val is not None:
                                    cand_rows.append(rows_val)
                            else:
                                cand_failed += 1

                    conn.rollback()

        except Exception as exc:
            err_msg = str(exc)
            err_lower = err_msg.lower()
            if self._is_run_cancelled(run_id) or " canceling statement due to user request" in err_lower or "cancelled" in err_lower:
                cancelled_occurred = True
            elif "statement timeout" in err_lower or "canceling statement due to statement timeout" in err_lower or "timeout" in err_lower and "connect" not in err_lower:
                timeout_occurred = True
                execution_error = f"Query exceeded sandbox statement_timeout of {statement_timeout_ms} ms."
            elif "does not exist" in err_lower or "undefinedtable" in err_lower or "undefinedcolumn" in err_lower or "read-only transaction" in err_lower:
                unsupported_reason = (
                    f"Sandbox environment cannot safely execute this statement ({type(exc).__name__}): "
                    f"{scrub_sql_text(err_msg)[:220]}"
                )
            else:
                execution_error = f"Sandbox connection or execution unavailable ({type(exc).__name__})."

        if cancelled_occurred:
            return self._build_non_executed_response(
                run_id=run_id,
                status="cancelled",
                reason="Benchmark run was cancelled during execution; sandbox transaction rolled back cleanly.",
                sanitized_baseline_sql=base_validation.sanitized_sql,
                sanitized_candidate_sql=cand_validation.sanitized_sql,
                candidate_index_ddl=safe_index_ddl,
                warmup_runs=warmup_runs,
                benchmark_runs=benchmark_runs,
                statement_timeout_ms=statement_timeout_ms,
                recommendation_id=recommendation_id,
            )

        if timeout_occurred:
            return self._build_non_executed_response(
                run_id=run_id,
                status="timeout",
                reason=execution_error or f"Benchmark exceeded statement_timeout of {statement_timeout_ms} ms.",
                sanitized_baseline_sql=base_validation.sanitized_sql,
                sanitized_candidate_sql=cand_validation.sanitized_sql,
                candidate_index_ddl=safe_index_ddl,
                warmup_runs=warmup_runs,
                benchmark_runs=benchmark_runs,
                statement_timeout_ms=statement_timeout_ms,
                recommendation_id=recommendation_id,
                timeout_occurred=True,
            )

        if unsupported_reason is not None:
            return self._build_non_executed_response(
                run_id=run_id,
                status="unsupported",
                reason=unsupported_reason,
                sanitized_baseline_sql=base_validation.sanitized_sql,
                sanitized_candidate_sql=cand_validation.sanitized_sql,
                candidate_index_ddl=safe_index_ddl,
                warmup_runs=warmup_runs,
                benchmark_runs=benchmark_runs,
                statement_timeout_ms=statement_timeout_ms,
                recommendation_id=recommendation_id,
            )

        # If sandbox was unreachable and caller provided fallback plans, produce estimate_only comparison (never fake ms!)
        if not base_samples_ms and not cand_samples_ms:
            if fallback_baseline_plan is not None and fallback_candidate_plan is not None:
                plan_diff = compare_execution_plans(
                    fallback_baseline_plan,
                    fallback_candidate_plan,
                    baseline_sql=base_validation.sanitized_sql,
                    candidate_sql=cand_validation.sanitized_sql,
                    candidate_index_ddl=safe_index_ddl,
                    recommendation_id=recommendation_id,
                )
                return {
                    "run_id": run_id,
                    "status": "estimate_only",
                    "comparison_verdict": "estimate_only",
                    "is_comparable": False,
                    "incomparability_reasons": [
                        execution_error
                        or "Sandbox database was unavailable for live execution; showing planner cost estimates only (no measured latency)."
                    ],
                    "cost_unit": COST_UNIT_LABEL,
                    "cost_disclaimer": COST_DISCLAIMER,
                    "safeguards": self._build_safeguards_summary(statement_timeout_ms),
                    "environment": self._build_environment_metadata(settings, warmup_runs, benchmark_runs, is_measured=False),
                    "baseline_metrics": summarize_benchmark_samples([], [], [], [], [], base_failed, warmup_runs, benchmark_runs),
                    "candidate_metrics": summarize_benchmark_samples([], [], [], [], [], cand_failed, warmup_runs, benchmark_runs),
                    "measured_comparison": {
                        "unit": "ms",
                        "is_measured": False,
                        "baseline_median_ms": None,
                        "candidate_median_ms": None,
                        "baseline_p95_ms": None,
                        "candidate_p95_ms": None,
                        "median_delta_ms": None,
                        "measured_speedup_pct": None,
                        "p95_speedup_pct": None,
                        "note": "No sandbox execution measurements collected. Planner cost units are shown separately and are not milliseconds.",
                    },
                    "estimated_cost_comparison": plan_diff["cost_comparison"],
                    "plan_comparison": plan_diff,
                    "provenance_state": ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value,
                    "provenance_badge": ProvenanceBadgeLabel.ESTIMATED.value,
                    "source_identifier": "planner:estimate_only",
                    "is_measured": False,
                    "is_synthetic": False,
                }

            return self._build_non_executed_response(
                run_id=run_id,
                status="failed",
                reason=execution_error or "Sandbox benchmark failed to collect execution samples.",
                sanitized_baseline_sql=base_validation.sanitized_sql,
                sanitized_candidate_sql=cand_validation.sanitized_sql,
                candidate_index_ddl=safe_index_ddl,
                warmup_runs=warmup_runs,
                benchmark_runs=benchmark_runs,
                statement_timeout_ms=statement_timeout_ms,
                recommendation_id=recommendation_id,
            )

        base_summary = summarize_benchmark_samples(
            base_samples_ms,
            base_warmup_ms,
            base_hits,
            base_reads,
            base_rows,
            base_failed,
            warmup_runs,
            benchmark_runs,
        )
        cand_summary = summarize_benchmark_samples(
            cand_samples_ms,
            cand_warmup_ms,
            cand_hits,
            cand_reads,
            cand_rows,
            cand_failed,
            warmup_runs,
            benchmark_runs,
        )

        plan_diff = compare_execution_plans(
            captured_base_plan or fallback_baseline_plan,
            captured_cand_plan or fallback_candidate_plan,
            baseline_sql=base_validation.sanitized_sql,
            candidate_sql=cand_validation.sanitized_sql,
            candidate_index_ddl=safe_index_ddl,
            recommendation_id=recommendation_id,
        )

        # Evaluate fair comparison & statistical significance
        incomparability_reasons: list[str] = []
        if base_summary["sample_count"] == 0 or cand_summary["sample_count"] == 0:
            incomparability_reasons.append("One or both variants have 0 completed measured samples.")
        if base_summary["sample_count"] != cand_summary["sample_count"]:
            incomparability_reasons.append(
                f"Mismatched sample sizes (baseline={base_summary['sample_count']}, candidate={cand_summary['sample_count']})."
            )
        if base_summary["failed_runs"] > 0 or cand_summary["failed_runs"] > 0:
            incomparability_reasons.append("One or more benchmark iterations failed during the test window.")
        if (
            base_summary["actual_rows"] is not None
            and cand_summary["actual_rows"] is not None
            and base_summary["actual_rows"] != cand_summary["actual_rows"]
        ):
            incomparability_reasons.append(
                f"Row count mismatch between baseline ({base_summary['actual_rows']}) and candidate "
                f"({cand_summary['actual_rows']}); queries may not be semantically equivalent."
            )

        is_comparable = len(incomparability_reasons) == 0
        b_med = base_summary["median_ms"]
        c_med = cand_summary["median_ms"]
        b_p95 = base_summary["p95_ms"]
        c_p95 = cand_summary["p95_ms"]

        median_delta_ms: float | None = None
        measured_speedup_pct: float | None = None
        p95_speedup_pct: float | None = None

        if b_med is not None and c_med is not None:
            median_delta_ms = round(c_med - b_med, 4)
            if b_med > 0:
                measured_speedup_pct = round(((b_med - c_med) / b_med) * 100.0, 2)
        if b_p95 is not None and c_p95 is not None and b_p95 > 0:
            p95_speedup_pct = round(((b_p95 - c_p95) / b_p95) * 100.0, 2)

        max_cv = max(
            base_summary["coefficient_of_variation"] or 0.0,
            cand_summary["coefficient_of_variation"] or 0.0,
        )
        rel_change = abs(measured_speedup_pct or 0.0) / 100.0

        if not is_comparable:
            comparison_verdict = "inconclusive"
            verdict_explanation = (
                "Comparison marked inconclusive due to incomparable test conditions: "
                + " ".join(incomparability_reasons)
            )
        elif b_med is None or c_med is None:
            comparison_verdict = "inconclusive"
            verdict_explanation = "Insufficient measured latency samples to determine improvement or regression."
        elif max_cv > 0.35 and rel_change < max_cv:
            comparison_verdict = "inconclusive"
            verdict_explanation = (
                f"Observed median latency change ({measured_speedup_pct:+.2f}%) is smaller than run-to-run "
                f"variability (CV={max_cv * 100.0:.1f}%). Increase warmup/benchmark runs for a conclusive result."
            )
        elif (measured_speedup_pct or 0.0) >= 5.0:
            comparison_verdict = "improved"
            verdict_explanation = (
                f"Candidate improved median sandbox execution time from {b_med:.2f} ms to {c_med:.2f} ms "
                f"({measured_speedup_pct:+.2f}% speedup; p95: {b_p95:.2f} ms -> {c_p95:.2f} ms). "
                f"Estimated planner cost changed separately from {plan_diff['cost_comparison']['baseline_total_cost']:.2f} "
                f"to {plan_diff['cost_comparison']['candidate_total_cost']:.2f} {COST_UNIT_LABEL}."
            )
        elif (measured_speedup_pct or 0.0) <= -5.0:
            comparison_verdict = "regressed"
            verdict_explanation = (
                f"REGRESSION DETECTED: Candidate degraded median sandbox execution time from {b_med:.2f} ms "
                f"to {c_med:.2f} ms ({measured_speedup_pct:+.2f}% slower; p95: {b_p95:.2f} ms -> {c_p95:.2f} ms)."
            )
        else:
            comparison_verdict = "inconclusive"
            verdict_explanation = (
                f"Candidate median latency ({c_med:.2f} ms) is within ±5% noise threshold of baseline ({b_med:.2f} ms)."
            )

        return {
            "run_id": run_id,
            "status": "completed",
            "comparison_verdict": comparison_verdict,
            "verdict_explanation": verdict_explanation,
            "is_comparable": is_comparable,
            "incomparability_reasons": incomparability_reasons,
            "cost_unit": COST_UNIT_LABEL,
            "cost_disclaimer": COST_DISCLAIMER,
            "safeguards": self._build_safeguards_summary(statement_timeout_ms),
            "environment": self._build_environment_metadata(settings, warmup_runs, benchmark_runs, is_measured=True),
            "baseline_metrics": base_summary,
            "candidate_metrics": cand_summary,
            "measured_comparison": {
                "unit": "ms",
                "is_measured": True,
                "baseline_median_ms": b_med,
                "candidate_median_ms": c_med,
                "baseline_p95_ms": b_p95,
                "candidate_p95_ms": c_p95,
                "median_delta_ms": median_delta_ms,
                "measured_speedup_pct": measured_speedup_pct,
                "p95_speedup_pct": p95_speedup_pct,
                "note": "Measured wall-clock execution time in isolated sandbox (milliseconds). Separate from planner cost units.",
            },
            "estimated_cost_comparison": plan_diff["cost_comparison"],
            "plan_comparison": plan_diff,
            "provenance_state": ProvenanceState.SANDBOX_BENCHMARK.value,
            "provenance_badge": ProvenanceBadgeLabel.SIMULATED.value,
            "source_identifier": "postgresql:sandbox_benchmark",
            "is_measured": True,
            "is_synthetic": False,
        }

    @staticmethod
    def _apply_session_safeguards(conn: Any, *, statement_timeout_ms: int, read_only: bool) -> None:
        conn.execute(text(f"SET LOCAL statement_timeout = '{int(statement_timeout_ms)}ms'"))
        conn.execute(text("SET LOCAL lock_timeout = '1000ms'"))
        conn.execute(text("SET LOCAL idle_in_transaction_session_timeout = '10000ms'"))
        conn.execute(text("SET LOCAL temp_file_limit = '64MB'"))
        conn.execute(text("SET LOCAL max_parallel_workers_per_gather = 0"))
        if read_only:
            conn.execute(text("SET LOCAL default_transaction_read_only = on"))
        else:
            conn.execute(text("SET LOCAL default_transaction_read_only = off"))

    @staticmethod
    def _run_single_explain_analyze(
        conn: Any, sql: str
    ) -> tuple[Any, float | None, int, int, float | None]:
        row = conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")).scalar()
        if isinstance(row, str):
            row = json.loads(row)
        tree = parse_plan_tree_detailed(row)
        return (
            row,
            tree.execution_time_ms,
            tree.total_shared_hit_blocks,
            tree.total_shared_read_blocks,
            tree.actual_rows,
        )

    @staticmethod
    def _build_safeguards_summary(statement_timeout_ms: int) -> dict[str, Any]:
        return {
            "isolated_sandbox_only": True,
            "production_execution_blocked": True,
            "read_only_transaction": True,
            "rolled_back_after_run": True,
            "statement_timeout_ms": statement_timeout_ms,
            "lock_timeout_ms": 1000,
            "temp_file_limit": "64MB",
            "max_parallel_workers_per_gather": 0,
            "max_concurrent_benchmarks": 2,
            "volatile_and_dml_statements_blocked": True,
            "read_only_limitation_note": (
                "Read-only transaction mode prevents DML/DDL writes during query execution, "
                "and is reinforced with AST validation, volatile-function blocking, statement_timeout, "
                "temp_file_limit, and an isolated sandbox database because read-only mode alone is not a complete sandbox."
            ),
        }

    @staticmethod
    def _build_environment_metadata(
        settings: Any, warmup_runs: int, benchmark_runs: int, *, is_measured: bool
    ) -> dict[str, Any]:
        return {
            "target": "isolated_sandbox_database" if is_measured else "planner_cost_estimator",
            "sandbox_max_rows_per_table": getattr(settings, "sandbox_max_rows_per_table", 25000),
            "warmup_runs": warmup_runs,
            "benchmark_runs": benchmark_runs,
            "parallel_workers_per_gather": 0,
            "cache_control_note": (
                f"{warmup_runs} warm-up run(s) executed prior to {benchmark_runs} measured run(s) "
                "to reduce cold buffer-cache bias; shared buffer hits vs. disk reads are recorded per series."
            ),
            "dataset_scale_note": (
                f"Sandbox tables are capped at {getattr(settings, 'sandbox_max_rows_per_table', 25000):,} rows. "
                "Sandbox timings verify directional plan behavior and relative speedup under controlled conditions."
            ),
        }

    def _build_non_executed_response(
        self,
        *,
        run_id: str,
        status: str,
        reason: str,
        sanitized_baseline_sql: str,
        sanitized_candidate_sql: str,
        candidate_index_ddl: str | None,
        warmup_runs: int,
        benchmark_runs: int,
        statement_timeout_ms: int,
        recommendation_id: int | None = None,
        timeout_occurred: bool = False,
    ) -> dict[str, Any]:
        settings = get_settings()
        empty_plan_diff = compare_execution_plans(
            None,
            None,
            baseline_sql=sanitized_baseline_sql,
            candidate_sql=sanitized_candidate_sql,
            candidate_index_ddl=candidate_index_ddl,
            recommendation_id=recommendation_id,
        )
        return {
            "run_id": run_id,
            "status": status,
            "comparison_verdict": status if status in {"unsupported", "timeout", "cancelled", "invalid_sql"} else "failed",
            "verdict_explanation": reason,
            "unsupported_reason": reason if status in {"unsupported", "invalid_sql"} else None,
            "error_reason": reason,
            "timeout_occurred": timeout_occurred,
            "cancelled": status == "cancelled",
            "is_comparable": False,
            "incomparability_reasons": [reason],
            "cost_unit": COST_UNIT_LABEL,
            "cost_disclaimer": COST_DISCLAIMER,
            "safeguards": self._build_safeguards_summary(statement_timeout_ms),
            "environment": self._build_environment_metadata(settings, warmup_runs, benchmark_runs, is_measured=False),
            "baseline_metrics": summarize_benchmark_samples([], [], [], [], [], 0, warmup_runs, benchmark_runs),
            "candidate_metrics": summarize_benchmark_samples([], [], [], [], [], 0, warmup_runs, benchmark_runs),
            "measured_comparison": {
                "unit": "ms",
                "is_measured": False,
                "baseline_median_ms": None,
                "candidate_median_ms": None,
                "baseline_p95_ms": None,
                "candidate_p95_ms": None,
                "median_delta_ms": None,
                "measured_speedup_pct": None,
                "p95_speedup_pct": None,
                "note": reason,
            },
            "estimated_cost_comparison": empty_plan_diff["cost_comparison"],
            "plan_comparison": empty_plan_diff,
            "provenance_state": ProvenanceState.HYPOTHETICAL_PLAN_ESTIMATE.value,
            "provenance_badge": "HYPOTHETICAL PLAN ESTIMATE",
            "source_identifier": "sandbox:not_executed",
            "is_measured": False,
            "is_synthetic": False,
        }


def export_plan_comparison_report(
    comparison_payload: dict[str, Any],
    *,
    export_format: str = "json",
    exported_by: str = "operator",
) -> tuple[str, str]:
    """Exports a sanitized plan comparison / benchmark report in JSON or CSV without leaking SQL literals."""
    plan_comp = comparison_payload.get("plan_comparison") or comparison_payload
    context = plan_comp.get("candidate_change_context") or {}

    safe_baseline_sql = scrub_sql_text(context.get("sanitized_baseline_sql") or "")
    safe_candidate_sql = scrub_sql_text(context.get("sanitized_candidate_sql") or "")

    cost_comp = plan_comp.get("cost_comparison") or {}
    actual_comp = plan_comp.get("actual_execution_comparison") or {}
    measured_comp = comparison_payload.get("measured_comparison") or {}
    node_diffs = plan_comp.get("node_diffs") or []

    # Sanitize every node diff explanation and condition to guarantee zero literal leakage
    safe_node_diffs: list[dict[str, Any]] = []
    for d in node_diffs:
        b_node = d.get("baseline_node") or {}
        c_node = d.get("candidate_node") or {}
        safe_node_diffs.append(
            {
                "diff_id": d.get("diff_id"),
                "change_type": d.get("change_type"),
                "severity": d.get("severity"),
                "relation_name": d.get("relation_name"),
                "baseline_operator": b_node.get("node_type"),
                "candidate_operator": c_node.get("node_type"),
                "baseline_index": b_node.get("index_name"),
                "candidate_index": c_node.get("index_name"),
                "baseline_total_cost_units": b_node.get("total_cost"),
                "candidate_total_cost_units": c_node.get("total_cost"),
                "baseline_estimated_rows": b_node.get("plan_rows"),
                "candidate_estimated_rows": c_node.get("plan_rows"),
                "baseline_actual_time_ms": b_node.get("inclusive_actual_time_ms"),
                "candidate_actual_time_ms": c_node.get("inclusive_actual_time_ms"),
                "baseline_shared_hit_blocks": b_node.get("shared_hit_blocks"),
                "candidate_shared_hit_blocks": c_node.get("shared_hit_blocks"),
                "baseline_shared_read_blocks": b_node.get("shared_read_blocks"),
                "candidate_shared_read_blocks": c_node.get("shared_read_blocks"),
                "baseline_filter_sanitized": _scrub_condition(b_node.get("filter_condition")),
                "candidate_filter_sanitized": _scrub_condition(c_node.get("filter_condition")),
                "explanation": d.get("explanation"),
            }
        )

    export_envelope = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_by": exported_by,
        "privacy_guaranteed": True,
        "literals_scrubbed": True,
        "cost_unit": COST_UNIT_LABEL,
        "cost_disclaimer": COST_DISCLAIMER,
        "verdict": comparison_payload.get("comparison_verdict") or plan_comp.get("verdict"),
        "narrative_explanation": comparison_payload.get("verdict_explanation")
        or plan_comp.get("narrative_explanation"),
        "candidate_change_context": {
            "sanitized_baseline_sql": safe_baseline_sql,
            "sanitized_candidate_sql": safe_candidate_sql,
            "candidate_index_ddl": context.get("candidate_index_ddl"),
            "recommendation_id": context.get("recommendation_id"),
        },
        "estimated_cost_comparison": cost_comp,
        "measured_execution_comparison": measured_comp if measured_comp else actual_comp,
        "baseline_metrics": comparison_payload.get("baseline_metrics"),
        "candidate_metrics": comparison_payload.get("candidate_metrics"),
        "node_diffs": safe_node_diffs,
    }

    fmt = (export_format or "json").strip().lower()
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "diff_id",
                "change_type",
                "severity",
                "relation_name",
                "baseline_operator",
                "candidate_operator",
                "baseline_index",
                "candidate_index",
                "baseline_total_cost_units (NOT_MS)",
                "candidate_total_cost_units (NOT_MS)",
                "baseline_estimated_rows",
                "candidate_estimated_rows",
                "baseline_actual_time_ms",
                "candidate_actual_time_ms",
                "baseline_shared_hit_blocks",
                "candidate_shared_hit_blocks",
                "baseline_shared_read_blocks",
                "candidate_shared_read_blocks",
                "explanation",
            ]
        )
        for row in safe_node_diffs:
            writer.writerow(
                [
                    row["diff_id"],
                    row["change_type"],
                    row["severity"],
                    row["relation_name"] or "",
                    row["baseline_operator"] or "",
                    row["candidate_operator"] or "",
                    row["baseline_index"] or "",
                    row["candidate_index"] or "",
                    row["baseline_total_cost_units"] if row["baseline_total_cost_units"] is not None else "",
                    row["candidate_total_cost_units"] if row["candidate_total_cost_units"] is not None else "",
                    row["baseline_estimated_rows"] if row["baseline_estimated_rows"] is not None else "",
                    row["candidate_estimated_rows"] if row["candidate_estimated_rows"] is not None else "",
                    row["baseline_actual_time_ms"] if row["baseline_actual_time_ms"] is not None else "",
                    row["candidate_actual_time_ms"] if row["candidate_actual_time_ms"] is not None else "",
                    row["baseline_shared_hit_blocks"] if row["baseline_shared_hit_blocks"] is not None else "",
                    row["candidate_shared_hit_blocks"] if row["candidate_shared_hit_blocks"] is not None else "",
                    row["baseline_shared_read_blocks"] if row["baseline_shared_read_blocks"] is not None else "",
                    row["candidate_shared_read_blocks"] if row["candidate_shared_read_blocks"] is not None else "",
                    row["explanation"] or "",
                ]
            )
        return "text/csv", buf.getvalue()

    return "application/json", json.dumps(export_envelope, indent=2, default=str)
