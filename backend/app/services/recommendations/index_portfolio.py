"""PostgreSQL Index Portfolio Advisor (Phase 8 Feature A).

Performs read-only catalog and workload analysis to:
1. Collect available index metadata using PostgreSQL catalog views (pg_indexes, pg_index,
   pg_class, pg_am, pg_stat_user_indexes, pg_stat_user_tables, pg_stat_database, pg_stats).
2. Identify potential duplicate or left-prefix overlapping B-tree indexes safely.
3. Identify indexes with low observed usage while accounting for statistics resets,
   index age, constraint enforcement, and workload coverage.
4. Analyze frequently filtered, joined, ordered, and grouped columns across workload telemetry.
5. Propose composite, partial, or single-column indexes only when supported by query evidence
   and valid PostgreSQL semantics, considering index size, write overhead, selectivity, and existing indexes.
6. Label missing or incomplete statistics and unsupported index types explicitly.
7. Never automatically drop or create any index — all outputs are reviewable candidates requiring DBA approval.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.provenance import (
    ProvenanceState,
    badge_for_state,
    compute_query_fingerprint,
    sanitize_source_identifier,
)
from app.models.relation import RelationStatistic
from app.models.workload import QueryStatistic
from app.services.recommendations.base import Recommendation
from app.services.recommendations.parsing import parse_query_shape

SUPPORTED_INDEX_ACCESS_METHODS = {"btree"}
KNOWN_NON_BTREE_METHODS = {"gin", "gist", "brin", "hash", "spgist", "bloom", "rum"}

_USING_RE = re.compile(r"\bUSING\s+([a-zA-Z0-9_]+)\b", re.I)
_INCLUDE_RE = re.compile(r"\bINCLUDE\s*\((.*?)\)", re.I | re.S)
_WHERE_RE = re.compile(r"\bWHERE\s+(.+)$", re.I | re.S)
_EQUALITY_PRED_RE = re.compile(
    r"\b([A-Za-z_\"][\w\"]*(?:\.[A-Za-z_\"][\w\"]*)?)\s*=\s*('[^']*'|\$\d+|\d+|true|false)",
    re.I,
)
_RANGE_PRED_RE = re.compile(
    r"\b([A-Za-z_\"][\w\"]*(?:\.[A-Za-z_\"][\w\"]*)?)\s*(?:<|>|<=|>=|\bBETWEEN\b)",
    re.I,
)
_IS_NOT_NULL_RE = re.compile(
    r"\b([A-Za-z_\"][\w\"]*(?:\.[A-Za-z_\"][\w\"]*)?)\s+IS\s+NOT\s+NULL\b",
    re.I,
)
_IS_NULL_RE = re.compile(
    r"\b([A-Za-z_\"][\w\"]*(?:\.[A-Za-z_\"][\w\"]*)?)\s+IS\s+NULL\b",
    re.I,
)


def parse_indexdef(indexdef: str | None) -> dict[str, Any]:
    """Parses a PostgreSQL CREATE [UNIQUE] INDEX definition string into structured metadata."""
    raw = (indexdef or "").strip()
    if not raw:
        return {
            "access_method": "btree",
            "columns": [],
            "column_directions": [],
            "included_columns": [],
            "predicate": None,
            "is_expression_index": False,
            "index_type_supported": True,
            "index_type_note": None,
        }

    using_m = _USING_RE.search(raw)
    access_method = using_m.group(1).lower() if using_m else "btree"

    # Extract WHERE partial predicate if present
    predicate: str | None = None
    where_m = _WHERE_RE.search(raw)
    work_str = raw
    if where_m:
        predicate = re.sub(r"\s+", " ", where_m.group(1).strip()).rstrip(";")
        work_str = raw[: where_m.start()].strip()

    # Extract INCLUDE (...) columns if present
    included_columns: list[str] = []
    inc_m = _INCLUDE_RE.search(work_str)
    if inc_m:
        included_columns = [
            c.strip().strip('"') for c in inc_m.group(1).split(",") if c.strip()
        ]
        work_str = work_str[: inc_m.start()].strip()

    # Extract key column list after USING <am> (...) or ON <table> (...)
    columns: list[str] = []
    column_directions: list[str] = []
    is_expression_index = False

    paren_start = work_str.find("(")
    paren_end = work_str.rfind(")")
    if paren_start != -1 and paren_end != -1 and paren_end > paren_start:
        inner = work_str[paren_start + 1 : paren_end].strip()
        # Split top-level comma-separated items respecting nested parens
        parts: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in inner:
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth = max(0, depth - 1)
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        if current:
            parts.append("".join(current).strip())

        for part in parts:
            if not part:
                continue
            dir_m = re.search(r"\b(ASC|DESC)\b", part, re.I)
            direction = dir_m.group(1).upper() if dir_m else "ASC"
            cleaned = re.sub(r"\s+(?:ASC|DESC)\b", "", part, flags=re.I)
            cleaned = re.sub(r"\s+NULLS\s+(?:FIRST|LAST)\b", "", cleaned, flags=re.I)
            cleaned = re.sub(r"\s+COLLATE\s+\S+", "", cleaned, flags=re.I).strip()
            # Strip operator class if present (e.g. "col varchar_pattern_ops")
            if "(" in cleaned or ")" in cleaned:
                is_expression_index = True
                columns.append(cleaned)
            else:
                tokens = cleaned.split()
                col_name = tokens[0].strip('"') if tokens else cleaned.strip('"')
                columns.append(col_name)
            column_directions.append(direction)

    supported = access_method in SUPPORTED_INDEX_ACCESS_METHODS
    note = None
    if not supported:
        note = (
            f"Index uses access method '{access_method.upper()}'. "
            "B-tree left-prefix overlap rules do not apply to non-B-tree index structures."
        )
    elif is_expression_index:
        note = "Functional/expression index detected; evaluate expression equivalence carefully before modifying."

    return {
        "access_method": access_method,
        "columns": columns,
        "column_directions": column_directions,
        "included_columns": included_columns,
        "predicate": predicate,
        "is_expression_index": is_expression_index,
        "index_type_supported": supported,
        "index_type_note": note,
    }


def _normalize_predicate(pred: str | None) -> str | None:
    if not pred:
        return None
    cleaned = re.sub(r"\s+", " ", pred.strip()).lower()
    while cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1].strip()
    return cleaned


class IndexPortfolioAdvisor:
    """Read-only PostgreSQL index portfolio analyzer and candidate generator."""

    def __init__(
        self,
        *,
        min_stats_age_seconds: int = 86400,
        low_usage_scan_threshold: int = 5,
    ) -> None:
        self.min_stats_age_seconds = min_stats_age_seconds
        self.low_usage_scan_threshold = low_usage_scan_threshold

    def analyze_portfolio(
        self,
        db: Session,
        *,
        schema_filter: str | None = None,
        table_filter: str | None = None,
        category_filter: str | None = None,
        access_method_filter: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 25,
        catalog_override: list[dict[str, Any]] | None = None,
        column_stats_override: dict[tuple[str, str], dict[str, Any]] | None = None,
        stats_reset_override: datetime | None = None,
        stats_reset_supplied: bool = False,
        workload_queries_override: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Performs a complete, read-only index portfolio analysis."""
        now = datetime.now(timezone.utc)
        settings = get_settings()
        default_source = sanitize_source_identifier(settings.database_url)

        # 1. Collect catalog metadata (read-only)
        if catalog_override is not None:
            raw_indexes = [self._enrich_raw_index(dict(item)) for item in catalog_override]
            stats_reset_at = stats_reset_override
            col_stats = column_stats_override if column_stats_override is not None else {}
            catalog_source = "supplied_schema_catalog"
            is_synthetic_catalog = False
        else:
            raw_indexes, stats_reset_at, col_stats, is_synthetic_catalog = self._collect_catalog_readonly(db)
            if stats_reset_supplied:
                stats_reset_at = stats_reset_override
            catalog_source = "synthetic://demo-catalog" if is_synthetic_catalog else default_source

        # 2. Load observed workload queries
        if workload_queries_override is not None:
            queries = list(workload_queries_override)
        else:
            queries = (
                db.scalars(
                    select(QueryStatistic)
                    .order_by(desc(QueryStatistic.total_exec_time_ms))
                    .limit(150)
                ).all()
                if db is not None
                else []
            )

        # 3. Evaluate statistics completeness & reset age
        stats_age_seconds: float | None = None
        if isinstance(stats_reset_at, datetime):
            reset_utc = stats_reset_at if stats_reset_at.tzinfo else stats_reset_at.replace(tzinfo=timezone.utc)
            stats_age_seconds = max(0.0, (now - reset_utc).total_seconds())

        stats_recently_reset = (
            stats_age_seconds is not None and stats_age_seconds < self.min_stats_age_seconds
        )
        stats_warnings: list[str] = []
        if stats_reset_at is None:
            stats_warnings.append(
                "pg_stat_database.stats_reset timestamp is unavailable; index scan counters have an unknown observation window."
            )
        elif stats_recently_reset:
            hours = round((stats_age_seconds or 0.0) / 3600.0, 2)
            stats_warnings.append(
                f"PostgreSQL statistics were reset {hours}h ago (< {round(self.min_stats_age_seconds / 3600, 1)}h window). "
                "Low idx_scan counters may reflect the short window after reset rather than true non-use."
            )

        missing_scan_counters = sum(1 for ix in raw_indexes if ix.get("idx_scan") is None)
        if missing_scan_counters > 0:
            stats_warnings.append(
                f"{missing_scan_counters} index(es) have missing pg_stat_user_indexes usage counters."
            )

        unsupported_indexes = [ix for ix in raw_indexes if not ix.get("index_type_supported", True)]
        if unsupported_indexes:
            methods = sorted({ix.get("access_method", "unknown").upper() for ix in unsupported_indexes})
            stats_warnings.append(
                f"{len(unsupported_indexes)} non-B-tree index(es) ({', '.join(methods)}) detected; "
                "B-tree left-prefix overlap rules are skipped for those indexes."
            )

        if not col_stats:
            stats_warnings.append(
                "Column selectivity statistics (pg_stats) are missing or incomplete; run ANALYZE on target relations for accurate n_distinct and null_frac estimates."
            )

        if missing_scan_counters == len(raw_indexes) and raw_indexes:
            completeness_status = "missing"
        elif stats_recently_reset:
            completeness_status = "recently_reset"
        elif stats_reset_at is None or missing_scan_counters > 0 or not col_stats:
            completeness_status = "partial"
        else:
            completeness_status = "complete"

        # 4. Analyze workload column access patterns (WHERE, JOIN, ORDER BY, GROUP BY)
        workload_analysis = self._analyze_workload_columns(queries)

        # 5. Detect duplicate & overlapping indexes
        overlapping_candidates, overlap_by_index = self._detect_overlapping_indexes(
            raw_indexes, workload_analysis["by_table"]
        )

        # 6. Detect low-usage indexes safely (accounting for stats reset, index age, constraints, workload coverage)
        low_usage_candidates, low_usage_by_index = self._detect_low_usage_indexes(
            raw_indexes,
            stats_reset_at=stats_reset_at,
            stats_age_seconds=stats_age_seconds,
            stats_recently_reset=stats_recently_reset,
            workload_by_table=workload_analysis["by_table"],
            total_workload_queries=len(queries),
        )

        # 7. Annotate every index in the inventory
        annotated_inventory: list[dict[str, Any]] = []
        for ix in raw_indexes:
            full_key = f"{ix['schema_name']}.{ix['index_name']}"
            ov = overlap_by_index.get(full_key)
            lu = low_usage_by_index.get(full_key)
            write_info = self._assess_table_write_overhead(ix, raw_indexes)

            if not ix.get("index_type_supported", True):
                category = "unsupported_type"
            elif ov is not None:
                category = "overlapping"
            elif lu is not None:
                category = "low_usage"
            else:
                category = "healthy"

            idx_stats_status = "complete"
            if ix.get("idx_scan") is None:
                idx_stats_status = "missing"
            elif stats_recently_reset:
                idx_stats_status = "recently_reset"
            elif stats_reset_at is None:
                idx_stats_status = "partial"

            annotated_inventory.append(
                {
                    **ix,
                    "category": category,
                    "statistics_status": idx_stats_status,
                    "stats_reset_at": stats_reset_at.isoformat() if isinstance(stats_reset_at, datetime) else None,
                    "stats_age_seconds": round(stats_age_seconds, 1) if stats_age_seconds is not None else None,
                    "stats_recently_reset": stats_recently_reset,
                    "write_overhead": write_info,
                    "overlap_finding": ov,
                    "low_usage_finding": lu,
                    "requires_dba_review": bool(ov is not None or lu is not None),
                    "auto_drop_permitted": False,
                }
            )

        # 8. Generate missing / composite / partial index proposals from workload + catalog
        missing_index_proposals, skipped_candidates = self._propose_workload_indexes(
            raw_indexes=raw_indexes,
            workload_analysis=workload_analysis,
            col_stats=col_stats,
        )

        # 9. Filter & paginate inventory
        filtered_inventory = annotated_inventory
        if schema_filter and schema_filter.strip() and schema_filter.strip().lower() != "all":
            sf = schema_filter.strip().lower()
            filtered_inventory = [i for i in filtered_inventory if i["schema_name"].lower() == sf]
        if table_filter and table_filter.strip() and table_filter.strip().lower() != "all":
            tf = table_filter.strip().lower()
            filtered_inventory = [i for i in filtered_inventory if i["table_name"].lower() == tf]
        if category_filter and category_filter.strip() and category_filter.strip().lower() != "all":
            cf = category_filter.strip().lower()
            filtered_inventory = [i for i in filtered_inventory if i["category"].lower() == cf]
        if access_method_filter and access_method_filter.strip() and access_method_filter.strip().lower() != "all":
            amf = access_method_filter.strip().lower()
            filtered_inventory = [i for i in filtered_inventory if i["access_method"].lower() == amf]
        if search and search.strip():
            q_str = search.strip().lower()
            filtered_inventory = [
                i
                for i in filtered_inventory
                if q_str in i["index_name"].lower()
                or q_str in i["table_name"].lower()
                or q_str in (i.get("indexdef") or "").lower()
                or any(q_str in c.lower() for c in i.get("columns", []))
            ]

        total_filtered = len(filtered_inventory)
        safe_page = max(1, page)
        safe_page_size = max(1, min(200, page_size))
        start_idx = (safe_page - 1) * safe_page_size
        paginated_inventory = filtered_inventory[start_idx : start_idx + safe_page_size]

        total_index_bytes = sum(int(i.get("index_size_bytes") or 0) for i in annotated_inventory)
        reclaimable_overlap_bytes = sum(int(c.get("index_size_bytes") or 0) for c in overlapping_candidates)

        prov_state = (
            ProvenanceState.SYNTHETIC_DEMO.value
            if is_synthetic_catalog
            else ProvenanceState.LIVE_TELEMETRY.value
        )

        return {
            "analyzed_at": now.isoformat(),
            "read_only_analysis": True,
            "auto_execution_permitted": False,
            "governance_notice": (
                "CANDIDATES REQUIRING DBA REVIEW: All index portfolio findings and SQL proposals are generated "
                "via read-only catalog inspection. DBZenith never automatically drops or creates indexes."
            ),
            "provenance_state": prov_state,
            "provenance_badge": badge_for_state(prov_state),
            "source_identifier": catalog_source,
            "statistics_completeness": {
                "status": completeness_status,
                "stats_reset_at": stats_reset_at.isoformat() if isinstance(stats_reset_at, datetime) else None,
                "stats_age_seconds": round(stats_age_seconds, 1) if stats_age_seconds is not None else None,
                "stats_recently_reset": stats_recently_reset,
                "min_recommended_stats_window_seconds": self.min_stats_age_seconds,
                "missing_scan_counter_count": missing_scan_counters,
                "unsupported_index_type_count": len(unsupported_indexes),
                "column_stats_tables_count": len({k[0] for k in col_stats.keys()}),
                "warnings": stats_warnings,
            },
            "summary": {
                "total_indexes": len(annotated_inventory),
                "total_index_size_bytes": total_index_bytes,
                "overlapping_candidates_count": len(overlapping_candidates),
                "reclaimable_overlap_bytes": reclaimable_overlap_bytes,
                "low_usage_candidates_count": len(low_usage_candidates),
                "missing_or_composite_proposals_count": len(missing_index_proposals),
                "unsupported_index_types_count": len(unsupported_indexes),
                "tables_covered": sorted({i["table_name"] for i in annotated_inventory}),
            },
            "inventory": {
                "items": paginated_inventory,
                "total": total_filtered,
                "page": safe_page,
                "page_size": safe_page_size,
            },
            "overlapping_candidates": overlapping_candidates,
            "low_usage_candidates": low_usage_candidates,
            "missing_index_proposals": missing_index_proposals,
            "skipped_candidates": skipped_candidates,
            "column_access_summary": workload_analysis["column_hotspots"],
        }

    def to_recommendations(self, db: Session, limit: int = 100) -> list[Recommendation]:
        """Converts portfolio advisor findings into Recommendation objects for the unified lifecycle."""
        report = self.analyze_portfolio(db, page=1, page_size=200)
        out: list[Recommendation] = []

        for ov in report["overlapping_candidates"]:
            raw_key = f"portfolio_overlap|{ov['schema_name']}|{ov['table_name']}|{ov['index_name']}|{ov['covering_index_name']}"
            key = hashlib.sha256(raw_key.encode()).hexdigest()
            out.append(
                Recommendation(
                    key=key,
                    type="redundant_index" if ov["overlap_type"] == "left_prefix_overlap" else "duplicate_index",
                    target=f"{ov['schema_name']}.{ov['index_name']}",
                    proposed_change=ov["reviewable_sql"],
                    reason=ov["rationale"],
                    evidence={
                        "advisor": "IndexPortfolioAdvisor",
                        "candidate_only_requires_dba_review": True,
                        "auto_drop_permitted": False,
                        "overlap_type": ov["overlap_type"],
                        "candidate_index": ov["index_name"],
                        "covering_index": ov["covering_index_name"],
                        "candidate_columns": ov["columns"],
                        "covering_columns": ov["covering_columns"],
                        "index_size_bytes": ov["index_size_bytes"],
                        "idx_scan": ov["idx_scan"],
                        "covering_idx_scan": ov["covering_idx_scan"],
                        "catalog_observations": ov["catalog_observations"],
                    },
                    expected_benefit=ov["expected_benefit"],
                    risk=ov["risk"],
                    confidence=ov["confidence"],
                    affected_queries=ov["supporting_queries"],
                    requires_approval=True,
                )
            )

        for prop in report["missing_index_proposals"]:
            raw_key = f"portfolio_proposal|{prop['proposal_type']}|{prop['table_name']}|{','.join(prop['columns'])}|{prop.get('partial_predicate') or ''}"
            key = hashlib.sha256(raw_key.encode()).hexdigest()
            out.append(
                Recommendation(
                    key=key,
                    type=prop["proposal_type"],
                    target=prop["table_name"],
                    proposed_change=prop["reviewable_sql"],
                    reason=prop["rationale"],
                    evidence={
                        "advisor": "IndexPortfolioAdvisor",
                        "candidate_only_requires_dba_review": True,
                        "columns": prop["columns"],
                        "partial_predicate": prop.get("partial_predicate"),
                        "estimated_index_size_bytes": prop.get("estimated_index_size_bytes"),
                        "write_overhead": prop.get("write_overhead"),
                        "selectivity": prop.get("selectivity"),
                        "catalog_observations": prop.get("catalog_observations"),
                    },
                    expected_benefit=prop["expected_benefit"],
                    risk=prop["risk"],
                    confidence=prop["confidence"],
                    affected_queries=prop["supporting_queries"],
                    requires_approval=True,
                )
            )
        return out[:limit]

    def _enrich_raw_index(self, item: dict[str, Any]) -> dict[str, Any]:
        indexdef = item.get("indexdef") or ""
        parsed = parse_indexdef(indexdef)
        cols = item.get("columns") if item.get("columns") is not None else parsed["columns"]
        access_method = (item.get("access_method") or parsed["access_method"] or "btree").lower()
        supported = access_method in SUPPORTED_INDEX_ACCESS_METHODS
        predicate = item.get("predicate") if "predicate" in item else parsed["predicate"]
        return {
            "schema_name": item.get("schema_name") or item.get("schemaname") or "public",
            "table_name": item.get("table_name") or item.get("tablename") or "unknown_table",
            "index_name": item.get("index_name") or item.get("indexname") or "unknown_index",
            "indexdef": indexdef,
            "access_method": access_method,
            "columns": list(cols),
            "column_directions": item.get("column_directions") or parsed["column_directions"],
            "included_columns": item.get("included_columns") or parsed["included_columns"],
            "predicate": predicate,
            "is_expression_index": bool(item.get("is_expression_index", parsed["is_expression_index"])),
            "index_type_supported": supported,
            "index_type_note": item.get("index_type_note") or parsed["index_type_note"],
            "is_unique": bool(item.get("is_unique", False)),
            "is_primary": bool(item.get("is_primary", False)),
            "is_valid": bool(item.get("is_valid", True)),
            "index_size_bytes": int(item.get("index_size_bytes") or 0),
            "table_size_bytes": int(item.get("table_size_bytes") or 0),
            "idx_scan": item.get("idx_scan") if "idx_scan" in item else 0,
            "idx_tup_read": int(item.get("idx_tup_read") or 0),
            "idx_tup_fetch": int(item.get("idx_tup_fetch") or 0),
            "table_seq_scan": int(item.get("table_seq_scan") or 0),
            "table_idx_scan": int(item.get("table_idx_scan") or 0),
            "n_tup_ins": int(item.get("n_tup_ins") or 0),
            "n_tup_upd": int(item.get("n_tup_upd") or 0),
            "n_tup_del": int(item.get("n_tup_del") or 0),
            "n_tup_hot_upd": int(item.get("n_tup_hot_upd") or 0),
            "n_live_tup": int(item.get("n_live_tup") or 0),
            "n_dead_tup": int(item.get("n_dead_tup") or 0),
            "index_created_at": item.get("index_created_at"),
            "index_age_seconds": item.get("index_age_seconds"),
        }

    def _collect_catalog_readonly(
        self, db: Session | None
    ) -> tuple[list[dict[str, Any]], datetime | None, dict[tuple[str, str], dict[str, Any]], bool]:
        if db is None:
            return self._synthetic_fallback_catalog(None)

        is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
        if is_pg:
            try:
                with db.begin_nested():
                    db.execute(text("SET LOCAL transaction_read_only = on"))
                    idx_rows = (
                        db.execute(
                            text(
                                """
                                SELECT
                                    i.schemaname AS schema_name,
                                    i.tablename AS table_name,
                                    i.indexname AS index_name,
                                    i.indexdef AS indexdef,
                                    am.amname AS access_method,
                                    ix.indisunique AS is_unique,
                                    ix.indisprimary AS is_primary,
                                    ix.indisvalid AS is_valid,
                                    pg_relation_size(c.oid) AS index_size_bytes,
                                    pg_total_relation_size(t.oid) AS table_size_bytes,
                                    sui.idx_scan AS idx_scan,
                                    COALESCE(sui.idx_tup_read, 0) AS idx_tup_read,
                                    COALESCE(sui.idx_tup_fetch, 0) AS idx_tup_fetch,
                                    COALESCE(sut.seq_scan, 0) AS table_seq_scan,
                                    COALESCE(sut.idx_scan, 0) AS table_idx_scan,
                                    COALESCE(sut.n_tup_ins, 0) AS n_tup_ins,
                                    COALESCE(sut.n_tup_upd, 0) AS n_tup_upd,
                                    COALESCE(sut.n_tup_del, 0) AS n_tup_del,
                                    COALESCE(sut.n_tup_hot_upd, 0) AS n_tup_hot_upd,
                                    COALESCE(sut.n_live_tup, 0) AS n_live_tup,
                                    COALESCE(sut.n_dead_tup, 0) AS n_dead_tup
                                FROM pg_indexes i
                                JOIN pg_namespace n ON n.nspname = i.schemaname
                                JOIN pg_class c ON c.relname = i.indexname AND c.relnamespace = n.oid
                                JOIN pg_index ix ON ix.indexrelid = c.oid
                                JOIN pg_class t ON t.oid = ix.indrelid
                                JOIN pg_am am ON am.oid = c.relam
                                LEFT JOIN pg_stat_user_indexes sui ON sui.indexrelid = c.oid
                                LEFT JOIN pg_stat_user_tables sut ON sut.relid = t.oid
                                WHERE i.schemaname NOT IN ('pg_catalog', 'information_schema')
                                  AND i.tablename NOT IN (
                                      'workload_snapshots', 'query_statistics', 'relation_statistics',
                                      'plan_analyses', 'optimization_recommendations', 'optimization_simulations',
                                      'recommendation_audit_events', 'privacy_audit_events', 'security_users',
                                      'security_audit_events', 'system_metadata', 'alembic_version',
                                      'workload_alert_rules', 'workload_alerts', 'alert_audit_events'
                                  )
                                ORDER BY pg_relation_size(c.oid) DESC, i.tablename ASC, i.indexname ASC
                                """
                            )
                        )
                        .mappings()
                        .all()
                    )

                    stats_reset_at = db.execute(
                        text("SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()")
                    ).scalar()

                    stat_rows = (
                        db.execute(
                            text(
                                """
                                SELECT tablename, attname, null_frac, n_distinct, correlation
                                FROM pg_stats
                                WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                                """
                            )
                        )
                        .mappings()
                        .all()
                    )
                    col_stats: dict[tuple[str, str], dict[str, Any]] = {}
                    for sr in stat_rows:
                        col_stats[(str(sr["tablename"]).lower(), str(sr["attname"]).lower())] = {
                            "null_frac": float(sr["null_frac"] or 0.0),
                            "n_distinct": float(sr["n_distinct"] or 0.0),
                            "correlation": float(sr["correlation"] or 0.0) if sr["correlation"] is not None else None,
                        }

                    enriched = [self._enrich_raw_index(dict(r)) for r in idx_rows]
                    if enriched:
                        return enriched, stats_reset_at, col_stats, False
            except Exception:
                pass

        return self._synthetic_fallback_catalog(db)

    def _synthetic_fallback_catalog(
        self, db: Session | None
    ) -> tuple[list[dict[str, Any]], datetime | None, dict[tuple[str, str], dict[str, Any]], bool]:
        """Provides a representative e-commerce index catalog when running in demo/SQLite mode."""
        rel_sizes: dict[str, dict[str, int]] = {}
        if db is not None:
            try:
                rels = db.scalars(select(RelationStatistic).limit(50)).all()
                for r in rels:
                    rel_sizes[r.relation_name.lower()] = {
                        "table_size_bytes": int(r.table_size_bytes or 24_500_000),
                        "index_size_bytes": int(r.index_size_bytes or 6_200_000),
                        "seq_scan": int(r.seq_scan or 1200),
                        "idx_scan": int(r.idx_scan or 4500),
                        "n_live_tup": int(r.n_live_tup or 150_000),
                        "n_dead_tup": int(r.n_dead_tup or 3_200),
                    }
            except Exception:
                pass

        orders_meta = rel_sizes.get("orders", {})
        t_size = orders_meta.get("table_size_bytes", 48_234_496)
        live_tup = orders_meta.get("n_live_tup", 250_000)

        demo_raw = [
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "orders_pkey",
                "indexdef": "CREATE UNIQUE INDEX orders_pkey ON public.orders USING btree (order_id)",
                "access_method": "btree",
                "is_unique": True,
                "is_primary": True,
                "index_size_bytes": 5_406_720,
                "table_size_bytes": t_size,
                "idx_scan": 48_920,
                "idx_tup_read": 195_000,
                "idx_tup_fetch": 182_000,
                "table_seq_scan": 3_420,
                "table_idx_scan": 64_100,
                "n_tup_ins": 18_500,
                "n_tup_upd": 6_400,
                "n_tup_del": 420,
                "n_live_tup": live_tup,
            },
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_customer_id",
                "indexdef": "CREATE INDEX idx_orders_customer_id ON public.orders USING btree (customer_id)",
                "access_method": "btree",
                "is_unique": False,
                "is_primary": False,
                "index_size_bytes": 5_382_144,
                "table_size_bytes": t_size,
                "idx_scan": 140,
                "idx_tup_read": 980,
                "idx_tup_fetch": 910,
                "table_seq_scan": 3_420,
                "table_idx_scan": 64_100,
                "n_tup_ins": 18_500,
                "n_tup_upd": 6_400,
                "n_tup_del": 420,
                "n_live_tup": live_tup,
            },
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_customer_order_date",
                "indexdef": "CREATE INDEX idx_orders_customer_order_date ON public.orders USING btree (customer_id, order_date DESC)",
                "access_method": "btree",
                "is_unique": False,
                "is_primary": False,
                "index_size_bytes": 8_126_464,
                "table_size_bytes": t_size,
                "idx_scan": 14_820,
                "idx_tup_read": 72_400,
                "idx_tup_fetch": 68_100,
                "table_seq_scan": 3_420,
                "table_idx_scan": 64_100,
                "n_tup_ins": 18_500,
                "n_tup_upd": 6_400,
                "n_tup_del": 420,
                "n_live_tup": live_tup,
            },
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_legacy_coupon_code",
                "indexdef": "CREATE INDEX idx_orders_legacy_coupon_code ON public.orders USING btree (coupon_code)",
                "access_method": "btree",
                "is_unique": False,
                "is_primary": False,
                "index_size_bytes": 4_194_304,
                "table_size_bytes": t_size,
                "idx_scan": 0,
                "idx_tup_read": 0,
                "idx_tup_fetch": 0,
                "table_seq_scan": 3_420,
                "table_idx_scan": 64_100,
                "n_tup_ins": 18_500,
                "n_tup_upd": 6_400,
                "n_tup_del": 420,
                "n_live_tup": live_tup,
            },
            {
                "schema_name": "public",
                "table_name": "customers",
                "index_name": "customers_pkey",
                "indexdef": "CREATE UNIQUE INDEX customers_pkey ON public.customers USING btree (customer_id)",
                "access_method": "btree",
                "is_unique": True,
                "is_primary": True,
                "index_size_bytes": 2_097_152,
                "table_size_bytes": 16_777_216,
                "idx_scan": 31_200,
                "idx_tup_read": 64_000,
                "idx_tup_fetch": 61_000,
                "table_seq_scan": 410,
                "table_idx_scan": 31_200,
                "n_tup_ins": 2_100,
                "n_tup_upd": 850,
                "n_tup_del": 15,
                "n_live_tup": 80_000,
            },
            {
                "schema_name": "public",
                "table_name": "products",
                "index_name": "idx_products_metadata_gin",
                "indexdef": "CREATE INDEX idx_products_metadata_gin ON public.products USING gin (attributes)",
                "access_method": "gin",
                "is_unique": False,
                "is_primary": False,
                "index_size_bytes": 3_145_728,
                "table_size_bytes": 12_582_912,
                "idx_scan": 840,
                "idx_tup_read": 4_200,
                "idx_tup_fetch": 3_900,
                "table_seq_scan": 190,
                "table_idx_scan": 9_400,
                "n_tup_ins": 340,
                "n_tup_upd": 520,
                "n_tup_del": 5,
                "n_live_tup": 25_000,
            },
        ]
        col_stats = {
            ("orders", "status"): {"null_frac": 0.0, "n_distinct": 5.0, "correlation": 0.22},
            ("orders", "order_date"): {"null_frac": 0.0, "n_distinct": -0.45, "correlation": 0.88},
            ("orders", "amount"): {"null_frac": 0.0, "n_distinct": 4500.0, "correlation": 0.12},
            ("orders", "customer_id"): {"null_frac": 0.0, "n_distinct": 42000.0, "correlation": 0.09},
            ("orders", "product_id"): {"null_frac": 0.0, "n_distinct": 12000.0, "correlation": 0.05},
            ("orders", "region_id"): {"null_frac": 0.0, "n_distinct": 12.0, "correlation": 0.31},
        }
        reset_time = datetime.now(timezone.utc).replace(microsecond=0)
        # Set demo stats reset to 7 days ago so baseline stats window is realistic unless overridden
        from datetime import timedelta

        reset_time = reset_time - timedelta(days=7)
        return [self._enrich_raw_index(r) for r in demo_raw], reset_time, col_stats, True

    def _assess_table_write_overhead(
        self, index_item: dict[str, Any], all_indexes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        table_name = index_item["table_name"].lower()
        schema_name = index_item["schema_name"].lower()
        same_table_indexes = [
            i
            for i in all_indexes
            if i["table_name"].lower() == table_name and i["schema_name"].lower() == schema_name
        ]
        write_tuples = (
            int(index_item.get("n_tup_ins") or 0)
            + int(index_item.get("n_tup_upd") or 0)
            + int(index_item.get("n_tup_del") or 0)
        )
        read_scans = int(index_item.get("table_seq_scan") or 0) + int(index_item.get("table_idx_scan") or 0)
        write_to_scan_ratio = round(write_tuples / max(1, read_scans + write_tuples), 3)
        hot_update_ratio = round(
            int(index_item.get("n_tup_hot_upd") or 0) / max(1, int(index_item.get("n_tup_upd") or 0)),
            3,
        )

        if len(same_table_indexes) >= 6 or write_to_scan_ratio >= 0.45:
            level = "high"
        elif len(same_table_indexes) >= 4 or write_to_scan_ratio >= 0.20:
            level = "moderate"
        else:
            level = "low"

        return {
            "level": level,
            "existing_index_count_on_table": len(same_table_indexes),
            "write_tuples_total": write_tuples,
            "read_scans_total": read_scans,
            "write_to_activity_ratio": write_to_scan_ratio,
            "hot_update_ratio": hot_update_ratio,
        }

    def _detect_overlapping_indexes(
        self,
        indexes: list[dict[str, Any]],
        workload_by_table: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        by_index: dict[str, dict[str, Any]] = {}

        for candidate in indexes:
            if candidate.get("is_primary"):
                continue
            cand_cols = [c.lower() for c in candidate.get("columns", [])]
            if not cand_cols:
                continue
            cand_am = candidate.get("access_method", "btree").lower()
            cand_pred = _normalize_predicate(candidate.get("predicate"))

            for covering in indexes:
                if covering is candidate:
                    continue
                if (
                    covering["schema_name"].lower() != candidate["schema_name"].lower()
                    or covering["table_name"].lower() != candidate["table_name"].lower()
                ):
                    continue
                cov_am = covering.get("access_method", "btree").lower()
                if cov_am != cand_am:
                    continue
                cov_cols = [c.lower() for c in covering.get("columns", [])]
                if not cov_cols:
                    continue
                cov_pred = _normalize_predicate(covering.get("predicate"))

                # Unique indexes cannot be dropped unless covered by an identical unique/PK index
                if candidate.get("is_unique") and not (
                    covering.get("is_unique") or covering.get("is_primary")
                ):
                    continue

                is_exact = (
                    cand_cols == cov_cols
                    and cand_pred == cov_pred
                    and candidate.get("column_directions", []) == covering.get("column_directions", [])
                )
                is_prefix = False
                if (
                    not is_exact
                    and cand_am in SUPPORTED_INDEX_ACCESS_METHODS
                    and not candidate.get("is_expression_index")
                    and not covering.get("is_expression_index")
                    and not candidate.get("is_unique")
                    and len(cand_cols) < len(cov_cols)
                    and cov_cols[: len(cand_cols)] == cand_cols
                ):
                    # Covering index must not have a narrower partial WHERE predicate than candidate
                    if cand_pred == cov_pred or (cand_pred is not None and cov_pred is None):
                        is_prefix = True

                if not (is_exact or is_prefix):
                    continue

                # Avoid emitting both (A covered by B) and (B covered by A) for exact duplicates
                if is_exact:
                    cand_scans = int(candidate.get("idx_scan") or 0)
                    cov_scans = int(covering.get("idx_scan") or 0)
                    if covering.get("is_primary") or covering.get("is_unique"):
                        pass
                    elif cand_scans > cov_scans or (
                        cand_scans == cov_scans and candidate["index_name"] < covering["index_name"]
                    ):
                        continue

                overlap_type = "exact_duplicate" if is_exact else "left_prefix_overlap"
                tbl_workload = workload_by_table.get(candidate["table_name"].lower(), {})
                supporting_queries = tbl_workload.get("queries", [])[:5]

                size_kb = round(int(candidate.get("index_size_bytes") or 0) / 1024.0, 1)
                reviewable_sql = (
                    f"-- CANDIDATE REQUIRING DBA REVIEW (NEVER AUTO-EXECUTED)\n"
                    f"-- Overlap type: {overlap_type} | Covering index: {covering['index_name']} ({', '.join(covering['columns'])})\n"
                    f"-- Verify pg_stat_user_indexes across a full business cycle before dropping:\n"
                    f"DROP INDEX CONCURRENTLY IF EXISTS {candidate['schema_name']}.{candidate['index_name']};"
                )
                rationale = (
                    f"Index '{candidate['index_name']}' on {candidate['schema_name']}.{candidate['table_name']} "
                    f"({', '.join(candidate['columns'])}) is an {overlap_type.replace('_', ' ')} of "
                    f"'{covering['index_name']}' ({', '.join(covering['columns'])})."
                )
                finding = {
                    "schema_name": candidate["schema_name"],
                    "table_name": candidate["table_name"],
                    "index_name": candidate["index_name"],
                    "access_method": cand_am,
                    "columns": candidate["columns"],
                    "predicate": candidate.get("predicate"),
                    "index_size_bytes": int(candidate.get("index_size_bytes") or 0),
                    "idx_scan": candidate.get("idx_scan"),
                    "covering_index_name": covering["index_name"],
                    "covering_columns": covering["columns"],
                    "covering_predicate": covering.get("predicate"),
                    "covering_index_size_bytes": int(covering.get("index_size_bytes") or 0),
                    "covering_idx_scan": covering.get("idx_scan"),
                    "overlap_type": overlap_type,
                    "rationale": rationale,
                    "expected_benefit": (
                        f"Reclaims ~{size_kb} KB of index storage and eliminates per-write B-tree maintenance "
                        f"on {candidate['table_name']} without losing leading-key access on ({', '.join(candidate['columns'])})."
                    ),
                    "risk": (
                        "Medium — narrower single-column indexes have smaller leaf pages than wide composite indexes; "
                        "verify with EXPLAIN / HypoPG that index-only scans or sort orders do not regress before dropping."
                    ),
                    "confidence": 0.88 if is_exact else 0.74,
                    "reviewable_sql": reviewable_sql,
                    "requires_dba_review": True,
                    "auto_drop_permitted": False,
                    "supporting_queries": supporting_queries,
                    "catalog_observations": {
                        "candidate_indexdef": candidate.get("indexdef"),
                        "covering_indexdef": covering.get("indexdef"),
                        "table_size_bytes": candidate.get("table_size_bytes"),
                        "n_tup_ins": candidate.get("n_tup_ins"),
                        "n_tup_upd": candidate.get("n_tup_upd"),
                        "n_tup_del": candidate.get("n_tup_del"),
                    },
                }
                candidates.append(finding)
                by_index[f"{candidate['schema_name']}.{candidate['index_name']}"] = finding
                break

        return candidates, by_index

    def _detect_low_usage_indexes(
        self,
        indexes: list[dict[str, Any]],
        *,
        stats_reset_at: datetime | None,
        stats_age_seconds: float | None,
        stats_recently_reset: bool,
        workload_by_table: dict[str, dict[str, Any]],
        total_workload_queries: int,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        by_index: dict[str, dict[str, Any]] = {}

        for ix in indexes:
            if ix.get("is_primary") or ix.get("is_unique"):
                continue
            scans = ix.get("idx_scan")
            if scans is None:
                # Missing statistics: do not claim low usage when scan counter is absent
                continue
            if int(scans) > self.low_usage_scan_threshold:
                continue

            tbl_key = ix["table_name"].lower()
            tbl_wl = workload_by_table.get(tbl_key, {})
            tbl_queries = tbl_wl.get("queries", [])
            lead_col = ix["columns"][0].lower() if ix.get("columns") else None
            referenced_by_workload = bool(
                lead_col and lead_col in tbl_wl.get("referenced_columns", set())
            )

            cautions: list[str] = [
                "Low or zero idx_scan in pg_stat_user_indexes NEVER automatically proves an index is unnecessary."
            ]
            if stats_reset_at is None:
                cautions.append(
                    "pg_stat_database.stats_reset timestamp is unknown; statistics may not cover periodic batch or reporting jobs."
                )
            elif stats_recently_reset:
                cautions.append(
                    f"Statistics were reset recently ({round((stats_age_seconds or 0.0) / 3600.0, 2)}h ago); "
                    "usage counters are too fresh to draw drop conclusions."
                )

            idx_age = ix.get("index_age_seconds")
            if idx_age is None:
                cautions.append(
                    "PostgreSQL does not natively record index creation timestamps; verify this index was not recently deployed."
                )
            elif float(idx_age) < self.min_stats_age_seconds:
                cautions.append(
                    f"Index was created recently ({round(float(idx_age) / 3600.0, 2)}h ago) and has not accumulated a full workload cycle."
                )

            if total_workload_queries < 5:
                cautions.append(
                    f"Observed workload coverage is small ({total_workload_queries} distinct query templates); "
                    "infrequent analytical or constraint queries may not be represented."
                )
            if referenced_by_workload:
                cautions.append(
                    f"Observed workload queries filter or join on '{lead_col}'; planner may prefer sequential scan at current table size or statistics."
                )

            advisory_status = (
                "caution_stats_recently_reset"
                if stats_recently_reset
                else ("caution_incomplete_stats" if stats_reset_at is None else "review_candidate")
            )
            confidence = 0.25 if stats_recently_reset else (0.35 if stats_reset_at is None else 0.55)
            size_kb = round(int(ix.get("index_size_bytes") or 0) / 1024.0, 1)

            reviewable_sql = (
                f"-- CANDIDATE FOR DBA REVIEW ONLY — DO NOT DROP AUTOMATICALLY\n"
                f"-- Observed idx_scan = {scans} | Advisory status: {advisory_status}\n"
                f"-- Step 1: Verify current scan counters and last stats reset:\n"
                f"SELECT schemaname, relname, indexrelname, idx_scan, idx_tup_read\n"
                f"FROM pg_stat_user_indexes WHERE schemaname = '{ix['schema_name']}' AND indexrelname = '{ix['index_name']}';\n"
                f"-- Step 2: Only after confirming across full monthly/quarterly cycles, consider:\n"
                f"-- DROP INDEX CONCURRENTLY IF EXISTS {ix['schema_name']}.{ix['index_name']};"
            )

            finding = {
                "schema_name": ix["schema_name"],
                "table_name": ix["table_name"],
                "index_name": ix["index_name"],
                "access_method": ix["access_method"],
                "columns": ix["columns"],
                "index_size_bytes": int(ix.get("index_size_bytes") or 0),
                "idx_scan": int(scans),
                "idx_tup_read": int(ix.get("idx_tup_read") or 0),
                "advisory_status": advisory_status,
                "stats_reset_at": stats_reset_at.isoformat() if isinstance(stats_reset_at, datetime) else None,
                "stats_age_seconds": round(stats_age_seconds, 1) if stats_age_seconds is not None else None,
                "stats_recently_reset": stats_recently_reset,
                "index_age_seconds": idx_age,
                "referenced_by_observed_queries": referenced_by_workload,
                "table_observed_query_count": len(tbl_queries),
                "cautions": cautions,
                "rationale": (
                    f"Index '{ix['index_name']}' on {ix['schema_name']}.{ix['table_name']} has {scans} observed scans "
                    f"(size: ~{size_kb} KB). {cautions[1] if len(cautions) > 1 else cautions[0]}"
                ),
                "expected_benefit": (
                    f"Potential to reclaim ~{size_kb} KB and reduce INSERT/UPDATE/DELETE index maintenance "
                    "if verified unused across all application and reporting workloads."
                ),
                "risk": (
                    "High if dropped prematurely — seasonal reports, foreign-key cascades, or replica read queries "
                    "may depend on this index. Never drop based solely on short-window idx_scan counters."
                ),
                "confidence": confidence,
                "reviewable_sql": reviewable_sql,
                "requires_dba_review": True,
                "auto_drop_permitted": False,
                "supporting_queries": tbl_queries[:5],
                "catalog_observations": {
                    "indexdef": ix.get("indexdef"),
                    "n_tup_ins": ix.get("n_tup_ins"),
                    "n_tup_upd": ix.get("n_tup_upd"),
                    "n_tup_del": ix.get("n_tup_del"),
                    "table_seq_scan": ix.get("table_seq_scan"),
                    "table_idx_scan": ix.get("table_idx_scan"),
                },
            }
            candidates.append(finding)
            by_index[f"{ix['schema_name']}.{ix['index_name']}"] = finding

        return candidates, by_index

    def _analyze_workload_columns(self, queries: list[Any]) -> dict[str, Any]:
        by_table: dict[str, dict[str, Any]] = {}
        column_stats_map: dict[tuple[str, str], dict[str, Any]] = {}
        composite_patterns: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
        partial_patterns: dict[tuple[str, tuple[str, ...], str], dict[str, Any]] = {}

        for q in queries:
            sql = getattr(q, "normalized_query", None) or (q.get("normalized_query") if isinstance(q, dict) else "") or ""
            if not sql.strip().lower().startswith(("select", "with")):
                continue
            qid = getattr(q, "query_id", None) if not isinstance(q, dict) else q.get("query_id")
            calls = int((getattr(q, "calls", 0) if not isinstance(q, dict) else q.get("calls", 0)) or 0)
            mean_ms = float((getattr(q, "mean_exec_time_ms", 0.0) if not isinstance(q, dict) else q.get("mean_exec_time_ms", 0.0)) or 0.0)
            total_ms = float((getattr(q, "total_exec_time_ms", 0.0) if not isinstance(q, dict) else q.get("total_exec_time_ms", 0.0)) or 0.0)
            blks_read = int((getattr(q, "shared_blks_read", 0) if not isinstance(q, dict) else q.get("shared_blks_read", 0)) or 0)
            q_fp = (
                getattr(q, "query_fingerprint", None)
                if not isinstance(q, dict)
                else q.get("query_fingerprint")
            ) or compute_query_fingerprint(sql)

            q_summary = {
                "query_id": qid,
                "query_fingerprint": q_fp,
                "normalized_query": sql[:240],
                "calls": calls,
                "mean_exec_time_ms": round(mean_ms, 2),
                "total_exec_time_ms": round(total_ms, 2),
                "shared_blks_read": blks_read,
            }

            shape = parse_query_shape(sql)
            for rel in shape.relations:
                r_low = rel.lower()
                entry = by_table.setdefault(
                    r_low,
                    {"table_name": rel, "queries": [], "referenced_columns": set()},
                )
                entry["queries"].append(q_summary)

            def _record_col(rel: str, col: str, role: str) -> None:
                if not rel or rel == "unknown_relation":
                    return
                r_low = rel.lower()
                c_low = col.lower()
                by_table.setdefault(
                    r_low, {"table_name": rel, "queries": [], "referenced_columns": set()}
                )["referenced_columns"].add(c_low)
                item = column_stats_map.setdefault(
                    (r_low, c_low),
                    {
                        "table_name": rel,
                        "column_name": col,
                        "filter_count": 0,
                        "join_count": 0,
                        "order_count": 0,
                        "group_count": 0,
                        "total_calls": 0,
                        "total_exec_time_ms": 0.0,
                        "shared_blks_read": 0,
                        "supporting_queries": [],
                    },
                )
                item[f"{role}_count"] += 1
                item["total_calls"] += calls
                item["total_exec_time_ms"] = round(item["total_exec_time_ms"] + total_ms, 2)
                item["shared_blks_read"] += blks_read
                if len(item["supporting_queries"]) < 5 and all(
                    sq.get("query_id") != qid for sq in item["supporting_queries"]
                ):
                    item["supporting_queries"].append(q_summary)

            for rel, col in shape.where_columns:
                _record_col(rel, col, "filter")
            for rel, col in shape.join_columns:
                _record_col(rel, col, "join")
            for rel, col, _dir in shape.order_columns:
                _record_col(rel, col, "order")
            if shape.relations:
                primary_rel = shape.relations[0]
                for col in shape.group_columns:
                    _record_col(primary_rel, col, "group")

            # Identify composite & partial index patterns per relation in this query
            where_by_rel: dict[str, list[str]] = {}
            for rel, col in shape.where_columns:
                if rel != "unknown_relation":
                    cols_list = where_by_rel.setdefault(rel.lower(), [])
                    if col.lower() not in cols_list:
                        cols_list.append(col.lower())

            order_by_rel: dict[str, list[str]] = {}
            for rel, col, _d in shape.order_columns:
                if rel != "unknown_relation":
                    cols_list = order_by_rel.setdefault(rel.lower(), [])
                    if col.lower() not in cols_list:
                        cols_list.append(col.lower())

            # Extract equality vs range columns from WHERE clause for proper B-tree key ordering
            eq_cols: set[str] = set()
            partial_pred_clauses: dict[str, str] = {}
            for m in _EQUALITY_PRED_RE.finditer(sql):
                token = m.group(1).strip('"')
                lit = m.group(2).strip()
                col_part = token.split(".")[-1].strip('"').lower()
                eq_cols.add(col_part)
                # Literal equality (non-parameter) can support a partial index when selective
                if not lit.startswith("$") and col_part in ("status", "state", "is_active", "active", "archived", "deleted"):
                    partial_pred_clauses[col_part] = f"{col_part} = {lit}"

            for m in _IS_NULL_RE.finditer(sql):
                col_part = m.group(1).split(".")[-1].strip('"').lower()
                if col_part in ("deleted_at", "archived_at", "processed_at"):
                    partial_pred_clauses[col_part] = f"{col_part} IS NULL"

            for m in _IS_NOT_NULL_RE.finditer(sql):
                col_part = m.group(1).split(".")[-1].strip('"').lower()
                partial_pred_clauses[col_part] = f"{col_part} IS NOT NULL"

            for rel_low, w_cols in where_by_rel.items():
                o_cols = [c for c in order_by_rel.get(rel_low, []) if c not in w_cols]
                # Order equality columns first, then remaining WHERE columns, then ORDER BY columns
                ordered_eq = [c for c in w_cols if c in eq_cols]
                ordered_range = [c for c in w_cols if c not in eq_cols]
                combined = (ordered_eq + ordered_range + o_cols)[:3]
                if len(combined) >= 2:
                    key_tuple = (rel_low, tuple(combined))
                    comp_item = composite_patterns.setdefault(
                        key_tuple,
                        {
                            "table_name": rel_low,
                            "columns": combined,
                            "equality_columns": ordered_eq,
                            "range_or_sort_columns": ordered_range + o_cols,
                            "total_calls": 0,
                            "total_exec_time_ms": 0.0,
                            "shared_blks_read": 0,
                            "supporting_queries": [],
                        },
                    )
                    comp_item["total_calls"] += calls
                    comp_item["total_exec_time_ms"] = round(comp_item["total_exec_time_ms"] + total_ms, 2)
                    comp_item["shared_blks_read"] += blks_read
                    if len(comp_item["supporting_queries"]) < 5:
                        comp_item["supporting_queries"].append(q_summary)

                # Partial index candidate when a constant filter is combined with another lookup/range/sort column
                for p_col, p_clause in partial_pred_clauses.items():
                    if p_col in w_cols:
                        other_cols = [c for c in combined if c != p_col]
                        target_cols = other_cols if other_cols else [p_col]
                        p_key = (rel_low, tuple(target_cols), p_clause)
                        p_item = partial_patterns.setdefault(
                            p_key,
                            {
                                "table_name": rel_low,
                                "columns": target_cols,
                                "partial_predicate": p_clause,
                                "predicate_column": p_col,
                                "total_calls": 0,
                                "total_exec_time_ms": 0.0,
                                "shared_blks_read": 0,
                                "supporting_queries": [],
                            },
                        )
                        p_item["total_calls"] += calls
                        p_item["total_exec_time_ms"] = round(p_item["total_exec_time_ms"] + total_ms, 2)
                        p_item["shared_blks_read"] += blks_read
                        if len(p_item["supporting_queries"]) < 5:
                            p_item["supporting_queries"].append(q_summary)

        hotspots = sorted(
            column_stats_map.values(),
            key=lambda x: (x["total_exec_time_ms"], x["total_calls"]),
            reverse=True,
        )
        return {
            "by_table": by_table,
            "column_hotspots": hotspots[:30],
            "composite_patterns": list(composite_patterns.values()),
            "partial_patterns": list(partial_patterns.values()),
        }

    def _propose_workload_indexes(
        self,
        *,
        raw_indexes: list[dict[str, Any]],
        workload_analysis: dict[str, Any],
        col_stats: dict[tuple[str, str], dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        proposals: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        seen_signatures: set[str] = set()

        def _is_covered(table: str, cols: list[str], pred: str | None = None) -> bool:
            t_low = table.lower()
            wanted = [c.lower() for c in cols]
            norm_pred = _normalize_predicate(pred)
            for ix in raw_indexes:
                if ix["table_name"].lower() != t_low:
                    continue
                if not ix.get("index_type_supported", True):
                    continue
                ix_cols = [c.lower() for c in ix.get("columns", [])]
                if ix_cols[: len(wanted)] == wanted:
                    ix_pred = _normalize_predicate(ix.get("predicate"))
                    if ix_pred is None or ix_pred == norm_pred:
                        return True
            return False

        def _table_context(table: str) -> dict[str, Any]:
            t_low = table.lower()
            matching = [i for i in raw_indexes if i["table_name"].lower() == t_low]
            if matching:
                sample = matching[0]
                write_info = self._assess_table_write_overhead(sample, raw_indexes)
                t_size = int(sample.get("table_size_bytes") or 0)
                live_tup = int(sample.get("n_live_tup") or 0)
            else:
                write_info = {
                    "level": "unknown",
                    "existing_index_count_on_table": 0,
                    "write_tuples_total": 0,
                    "read_scans_total": 0,
                    "write_to_activity_ratio": 0.0,
                    "hot_update_ratio": 0.0,
                }
                t_size = 0
                live_tup = 0
            return {
                "existing_indexes": [i["index_name"] for i in matching],
                "existing_index_count": len(matching),
                "table_size_bytes": t_size,
                "n_live_tup": live_tup,
                "write_overhead": write_info,
            }

        def _selectivity_info(table: str, cols: list[str]) -> dict[str, Any]:
            t_low = table.lower()
            col_details = []
            has_stats = False
            low_selectivity = False
            for c in cols:
                st = col_stats.get((t_low, c.lower()))
                if st is not None:
                    has_stats = True
                    nd = st["n_distinct"]
                    nf = st["null_frac"]
                    # In pg_stats, n_distinct > 0 is absolute distinct count; < 0 is fraction of rows
                    if 0 < nd <= 3:
                        low_selectivity = True
                    col_details.append({"column": c, "n_distinct": nd, "null_frac": nf, "status": "available"})
                else:
                    col_details.append({"column": c, "n_distinct": None, "null_frac": None, "status": "missing"})
            return {
                "statistics_status": "available" if has_stats else "missing",
                "low_selectivity_flag": low_selectivity and len(cols) == 1,
                "columns": col_details,
            }

        # 1. Composite B-tree proposals
        for comp in sorted(
            workload_analysis["composite_patterns"],
            key=lambda x: x["total_exec_time_ms"],
            reverse=True,
        ):
            table = comp["table_name"]
            cols = comp["columns"]
            if _is_covered(table, cols):
                continue
            sig = f"composite|{table}|{','.join(cols)}"
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

            t_ctx = _table_context(table)
            sel_info = _selectivity_info(table, cols)
            est_size = (
                int(t_ctx["table_size_bytes"] * min(0.35, 0.10 + 0.06 * len(cols)))
                if t_ctx["table_size_bytes"] > 0
                else None
            )
            idx_name = f"idx_{table}_{'_'.join(cols)}"[:63]
            ddl = (
                f"-- CANDIDATE REQUIRING DBA REVIEW (NEVER AUTO-EXECUTED)\n"
                f"CREATE INDEX CONCURRENTLY {idx_name} ON {table} ({', '.join(cols)});"
            )
            write_lvl = t_ctx["write_overhead"]["level"]
            proposals.append(
                {
                    "proposal_type": "composite_index",
                    "table_name": table,
                    "columns": cols,
                    "partial_predicate": None,
                    "index_name_suggestion": idx_name,
                    "reviewable_sql": ddl,
                    "rationale": (
                        f"Queries on '{table}' repeatedly filter/order across ({', '.join(cols)}) "
                        f"accumulating {comp['total_exec_time_ms']} ms total execution time across {comp['total_calls']} calls. "
                        f"Equality keys ({', '.join(comp['equality_columns']) or cols[0]}) are placed ahead of range/sort keys "
                        "to satisfy PostgreSQL B-tree composite prefix semantics."
                    ),
                    "expected_benefit": (
                        "Enables single-pass B-tree range scan and/or ordered retrieval without heap re-sorting."
                    ),
                    "risk": (
                        f"Write overhead is '{write_lvl}' ({t_ctx['existing_index_count']} existing indexes on {table}). "
                        "Validate in HypoPG sandbox and check write amplification before deployment."
                    ),
                    "confidence": 0.86 if sel_info["statistics_status"] == "available" else 0.72,
                    "estimated_index_size_bytes": est_size,
                    "write_overhead": t_ctx["write_overhead"],
                    "selectivity": sel_info,
                    "supporting_queries": comp["supporting_queries"],
                    "catalog_observations": t_ctx,
                    "requires_dba_review": True,
                }
            )

        # 2. Partial B-tree proposals
        for part in sorted(
            workload_analysis["partial_patterns"],
            key=lambda x: x["total_exec_time_ms"],
            reverse=True,
        ):
            table = part["table_name"]
            cols = part["columns"]
            pred = part["partial_predicate"]
            if _is_covered(table, cols, pred):
                continue
            sig = f"partial|{table}|{','.join(cols)}|{pred}"
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

            t_ctx = _table_context(table)
            sel_info = _selectivity_info(table, cols + [part["predicate_column"]])
            est_size = (
                int(t_ctx["table_size_bytes"] * 0.06)
                if t_ctx["table_size_bytes"] > 0
                else None
            )
            idx_name = f"idx_{table}_{'_'.join(cols)}_partial"[:63]
            ddl = (
                f"-- CANDIDATE REQUIRING DBA REVIEW (NEVER AUTO-EXECUTED)\n"
                f"CREATE INDEX CONCURRENTLY {idx_name} ON {table} ({', '.join(cols)}) WHERE {pred};"
            )
            proposals.append(
                {
                    "proposal_type": "partial_index",
                    "table_name": table,
                    "columns": cols,
                    "partial_predicate": pred,
                    "index_name_suggestion": idx_name,
                    "reviewable_sql": ddl,
                    "rationale": (
                        f"Queries on '{table}' repeatedly filter on constant predicate 'WHERE {pred}' "
                        f"with lookup/sort on ({', '.join(cols)}). A partial B-tree index indexes only matching rows, "
                        "reducing index footprint and write maintenance on non-matching rows."
                    ),
                    "expected_benefit": (
                        "Smaller B-tree depth and lower buffer footprint compared to a full-table index."
                    ),
                    "risk": (
                        "PostgreSQL can only use a partial index when the query's WHERE clause provably implies "
                        f"'{pred}' (unparameterized constant or matching partial predicate)."
                    ),
                    "confidence": 0.82 if sel_info["statistics_status"] == "available" else 0.70,
                    "estimated_index_size_bytes": est_size,
                    "write_overhead": t_ctx["write_overhead"],
                    "selectivity": sel_info,
                    "supporting_queries": part["supporting_queries"],
                    "catalog_observations": t_ctx,
                    "requires_dba_review": True,
                }
            )

        # 3. Single-column B-tree proposals (with low-selectivity guard)
        for hs in workload_analysis["column_hotspots"]:
            table = hs["table_name"]
            col = hs["column_name"]
            if _is_covered(table, [col]):
                continue
            t_ctx = _table_context(table)
            sel_info = _selectivity_info(table, [col])
            if sel_info["low_selectivity_flag"]:
                skipped.append(
                    {
                        "table_name": table,
                        "columns": [col],
                        "reason": (
                            f"Skipped single-column B-tree index on {table}.{col}: pg_stats indicates very low cardinality "
                            f"(n_distinct={sel_info['columns'][0]['n_distinct']}). Consider a composite or partial index instead."
                        ),
                    }
                )
                continue

            sig = f"single|{table}|{col.lower()}"
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

            est_size = (
                int(t_ctx["table_size_bytes"] * 0.11)
                if t_ctx["table_size_bytes"] > 0
                else None
            )
            idx_name = f"idx_{table.lower()}_{col.lower()}"[:63]
            ddl = (
                f"-- CANDIDATE REQUIRING DBA REVIEW (NEVER AUTO-EXECUTED)\n"
                f"CREATE INDEX CONCURRENTLY {idx_name} ON {table} ({col});"
            )
            proposals.append(
                {
                    "proposal_type": "index_where" if hs["filter_count"] >= hs["join_count"] else "index_join",
                    "table_name": table,
                    "columns": [col],
                    "partial_predicate": None,
                    "index_name_suggestion": idx_name,
                    "reviewable_sql": ddl,
                    "rationale": (
                        f"Column {table}.{col} is accessed in {hs['filter_count']} filter(s), {hs['join_count']} join(s), "
                        f"and {hs['order_count']} sort(s) ({hs['total_calls']} calls, {hs['total_exec_time_ms']} ms total) "
                        "and is not covered by the leading key of any existing B-tree index."
                    ),
                    "expected_benefit": "Reduces sequential heap scans for selective predicate or join lookups.",
                    "risk": (
                        f"Table write overhead is '{t_ctx['write_overhead']['level']}'. "
                        + (
                            "Column statistics (pg_stats) are missing; run ANALYZE to confirm cardinality before creating."
                            if sel_info["statistics_status"] == "missing"
                            else "Verify cardinality and write workload before approval."
                        )
                    ),
                    "confidence": 0.80 if sel_info["statistics_status"] == "available" else 0.65,
                    "estimated_index_size_bytes": est_size,
                    "write_overhead": t_ctx["write_overhead"],
                    "selectivity": sel_info,
                    "supporting_queries": hs["supporting_queries"],
                    "catalog_observations": t_ctx,
                    "requires_dba_review": True,
                }
            )

        return proposals[:25], skipped
