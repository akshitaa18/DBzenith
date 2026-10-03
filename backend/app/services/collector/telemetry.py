from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.relation import RelationStatistic
from app.models.workload import QueryStatistic, WorkloadSnapshot

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")


def normalize_query(query: str) -> str:
    return _WS.sub(" ", query).strip()


class TelemetryCollector:
    """Collects real PostgreSQL statistics from pg_stat_statements.

    No application-side mock statistics are generated. Optional pg_qualstats
    data is joined when that extension is installed.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def collect_once(self) -> WorkloadSnapshot:
        started = time.monotonic()
        session_factory = get_session_factory()
        with session_factory() as db:
            rows = self._query_stats(db)
            predicates = self._predicate_stats(db)
            relations = self._relation_stats(db)
            previous = self._previous_snapshot(db)
            snapshot = WorkloadSnapshot(
                window_seconds=self._window_seconds(db),
                total_calls=sum(int(r["calls"] or 0) for r in rows),
                total_exec_time_ms=sum(float(r["total_exec_time"] or 0) for r in rows),
                unique_queries=len(rows),
                slow_queries=sum(
                    1 for r in rows if float(r["mean_exec_time"] or 0) >= self.settings.slow_query_threshold_ms
                ),
            )
            db.add(snapshot)
            db.flush()

            elapsed_window = snapshot.window_seconds
            for relation in relations:
                db.add(RelationStatistic(snapshot_id=snapshot.id, **relation))

            for row_index, row in enumerate(rows):
                query_id = int(row["queryid"])
                previous_calls = previous.get(query_id, (0, snapshot.captured_at))
                delta_calls = max(0, int(row["calls"] or 0) - previous_calls[0])
                frequency = (
                    delta_calls / elapsed_window * 60.0
                    if elapsed_window > 0
                    else 0.0
                )
                explain_plan = None
                if (self.settings.collect_explain and row_index < self.settings.explain_query_limit
                        and self._is_safe_explain_candidate(row["query"] or "")):
                    explain_plan = self._explain(db, row["query"] or "")

                db.add(
                    QueryStatistic(
                        snapshot_id=snapshot.id,
                        query_id=query_id,
                        database_oid=int(row["dbid"] or 0),
                        user_oid=int(row["userid"] or 0),
                        database_name=row["database_name"],
                        user_name=row["user_name"],
                        normalized_query=normalize_query(row["query"] or ""),
                        calls=int(row["calls"] or 0),
                        total_exec_time_ms=float(row["total_exec_time"] or 0),
                        mean_exec_time_ms=float(row["mean_exec_time"] or 0),
                        min_exec_time_ms=float(row["min_exec_time"] or 0),
                        max_exec_time_ms=float(row["max_exec_time"] or 0),
                        rows=int(row["rows"] or 0),
                        shared_blks_hit=int(row["shared_blks_hit"] or 0),
                        shared_blks_read=int(row["shared_blks_read"] or 0),
                        shared_blks_dirtied=int(row["shared_blks_dirtied"] or 0),
                        shared_blks_written=int(row["shared_blks_written"] or 0),
                        local_blks_hit=int(row["local_blks_hit"] or 0),
                        local_blks_read=int(row["local_blks_read"] or 0),
                        temp_blks_read=int(row["temp_blks_read"] or 0),
                        temp_blks_written=int(row["temp_blks_written"] or 0),
                        blk_read_time_ms=float(row["blk_read_time"] or 0),
                        blk_write_time_ms=float(row["blk_write_time"] or 0),
                        query_frequency_per_minute=frequency,
                        predicate_info=predicates.get(query_id),
                        explain_plan=explain_plan,
                    )
                )
            db.commit()
            db.refresh(snapshot)
            logger.info(
                "telemetry_snapshot_collected",
                extra={
                    "event": "telemetry_snapshot_collected",
                    "snapshot_id": snapshot.id,
                    "query_count": snapshot.unique_queries,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )
            return snapshot

    def _query_stats(self, db: Session) -> list[dict]:
        # Check available columns in pg_stat_statements for compatibility with PG17+ and older versions
        col_rows = db.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'pg_stat_statements'")
        ).fetchall()
        col_names = {r[0] for r in col_rows}

        if "blk_read_time" in col_names:
            blk_read_expr = "s.blk_read_time"
            blk_write_expr = "s.blk_write_time"
        elif "shared_blk_read_time" in col_names:
            blk_read_expr = "COALESCE(s.shared_blk_read_time + s.local_blk_read_time, 0.0) AS blk_read_time"
            blk_write_expr = "COALESCE(s.shared_blk_write_time + s.local_blk_write_time, 0.0) AS blk_write_time"
        else:
            blk_read_expr = "0.0 AS blk_read_time"
            blk_write_expr = "0.0 AS blk_write_time"

        query_sql = f"""
            SELECT
                s.userid,
                s.dbid,
                s.queryid,
                s.query,
                s.calls,
                s.total_exec_time,
                s.mean_exec_time,
                s.min_exec_time,
                s.max_exec_time,
                s.rows,
                s.shared_blks_hit,
                s.shared_blks_read,
                s.shared_blks_dirtied,
                s.shared_blks_written,
                s.local_blks_hit,
                s.local_blks_read,
                s.temp_blks_read,
                s.temp_blks_written,
                {blk_read_expr},
                {blk_write_expr},
                d.datname AS database_name,
                u.rolname AS user_name
            FROM pg_stat_statements s
            LEFT JOIN pg_database d ON d.oid = s.dbid
            LEFT JOIN pg_roles u ON u.oid = s.userid
            WHERE s.queryid IS NOT NULL
              AND s.dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
            ORDER BY s.total_exec_time DESC
            LIMIT :limit
        """
        result = db.execute(text(query_sql), {"limit": self.settings.telemetry_query_limit}).mappings().all()
        return [dict(row) for row in result]

    def _relation_stats(self, db: Session) -> list[dict]:
        rows = db.execute(
            text(
                """
                SELECT
                    s.schemaname AS schema_name,
                    s.relname AS relation_name,
                    s.seq_scan,
                    s.idx_scan,
                    s.n_live_tup,
                    s.n_dead_tup,
                    pg_total_relation_size(s.relid) AS table_size_bytes,
                    COALESCE(pg_indexes_size(s.relid), 0) AS index_size_bytes
                FROM pg_stat_user_tables s
                ORDER BY pg_total_relation_size(s.relid) DESC
                LIMIT :limit
                """
            ),
            {"limit": self.settings.telemetry_relation_limit},
        ).mappings().all()
        return [dict(row) for row in rows]

    def _predicate_stats(self, db: Session) -> dict[int, dict]:
        exists = db.execute(
            text("SELECT to_regclass('public.pg_qualstats') IS NOT NULL")
        ).scalar()
        if not exists:
            return {}
        try:
            with db.begin_nested():
                rows = db.execute(
                    text(
                        """
                        SELECT queryid,
                               count(*) AS predicate_count,
                               coalesce(sum(occurences), 0) AS predicate_occurrences,
                               coalesce(sum(execution_count), 0) AS predicate_execution_count,
                               coalesce(sum(nbfiltered), 0) AS rows_filtered,
                               array_agg(DISTINCT eval_type) AS evaluation_types
                        FROM pg_qualstats
                        WHERE queryid IS NOT NULL
                        GROUP BY queryid
                        """
                    )
                ).mappings().all()
            return {
                int(r["queryid"]): {
                    "predicate_count": int(r["predicate_count"] or 0),
                    "predicate_occurrences": int(r["predicate_occurrences"] or 0),
                    "predicate_execution_count": int(r["predicate_execution_count"] or 0),
                    "rows_filtered": int(r["rows_filtered"] or 0),
                    "evaluation_types": r["evaluation_types"] or [],
                }
                for r in rows
            }
        except Exception:
            logger.warning("pg_qualstats_query_failed", exc_info=True)
            return {}

    def _previous_snapshot(self, db: Session) -> dict[int, tuple[int, datetime]]:
        rows = db.execute(
            text(
                """
                SELECT qs.query_id, qs.calls, ws.captured_at
                FROM query_statistics qs
                JOIN workload_snapshots ws ON ws.id = qs.snapshot_id
                WHERE ws.id = (
                    SELECT id FROM workload_snapshots ORDER BY captured_at DESC, id DESC LIMIT 1
                )
                """
            )
        ).all()
        return {int(r[0]): (int(r[1]), r[2]) for r in rows}

    def _window_seconds(self, db: Session) -> float:
        row = db.execute(
            text(
                """
                SELECT EXTRACT(EPOCH FROM (now() - max(captured_at)))
                FROM workload_snapshots
                """
            )
        ).scalar()
        if row is None:
            return float(self.settings.telemetry_interval_seconds)
        return max(float(row), 0.001)

    @staticmethod
    def _is_safe_explain_candidate(query: str) -> bool:
        cleaned = query.lstrip().lower()
        return cleaned.startswith(("select ", "with ", "values ", "show "))

    def _explain(self, db: Session, query: str) -> list | dict | None:
        if "$" in query:
            return None
        try:
            with db.begin_nested():
                row = db.execute(
                    text("EXPLAIN (FORMAT JSON, COSTS TRUE, VERBOSE FALSE) " + query)
                ).scalar_one()
            return row
        except Exception:
            return None


class TelemetryWorker:
    def __init__(self) -> None:
        self.collector = TelemetryCollector()
        self.settings = get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="dbzenith-telemetry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        try:
            self.collector.collect_once()
        except Exception:
            logger.exception("initial_telemetry_collection_failed")
        while not self._stop.wait(self.settings.telemetry_interval_seconds):
            try:
                self.collector.collect_once()
            except Exception:
                logger.exception("telemetry_collection_failed")
