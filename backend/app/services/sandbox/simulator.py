from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable, Index, PrimaryKeyConstraint
from sqlalchemy.sql.sqltypes import NullType
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.recommendation import OptimizationRecommendation
from app.models.simulation import OptimizationSimulation
from app.models.workload import QueryStatistic
from app.services.recommendations.parsing import parse_query_shape


_SIMULATION_LOCK = Lock()
_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_INDEX_CHANGE = re.compile(
    r"^\s*CREATE\s+INDEX(?:\s+CONCURRENTLY)?(?:\s+IF\s+NOT\s+EXISTS)?"
    r"(?:\s+(?P<index>[A-Za-z_][A-Za-z0-9_]*))?\s+ON\s+"
    r"(?:(?P<schema>[A-Za-z_][A-Za-z0-9_]*)\.)?(?P<table>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\((?P<columns>.+)\)\s*;?\s*$",
    re.I | re.S,
)


@dataclass(frozen=True)
class IndexSpec:
    table_schema: str
    table_name: str
    columns_sql: str
    index_name: str | None


class SandboxSimulator:
    """Runs optimization experiments exclusively against the sandbox database."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._engine = create_engine(self.settings.sandbox_database_url, pool_pre_ping=True, future=True)

    def simulate(self, db: Session, recommendation: OptimizationRecommendation, request: Any) -> OptimizationSimulation:
        row = OptimizationSimulation(
            recommendation_id=recommendation.id,
            status="running",
            affected_queries=[], plan_differences=[], estimated_storage_impact={},
            write_overhead_estimate={}, limitations=[], benchmark={}, baseline_plans=[], proposed_plans=[],
            confidence=0.0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        try:
            if recommendation.type not in {"index_where", "index_join", "index_order_by", "composite_index"}:
                raise ValueError("simulation currently supports index recommendations only")
            with _SIMULATION_LOCK:
                result = self._run(db, recommendation, request)
            for key, value in result.items():
                setattr(row, key, value)
            row.status = "completed"
            db.commit()
            db.refresh(row)
            return row
        except Exception as exc:
            row.status = "failed"
            row.error = str(exc)[:4000]
            row.limitations = [
                "Simulation failed before a complete comparison was produced.",
                "No production DDL or production benchmark was executed.",
            ]
            db.commit()
            db.refresh(row)
            return row

    def _run(self, db: Session, recommendation: OptimizationRecommendation, request: Any) -> dict[str, Any]:
        request.max_rows_per_table = min(request.max_rows_per_table, self.settings.simulation_max_rows_per_table)
        request.statement_timeout_ms = min(request.statement_timeout_ms, self.settings.simulation_max_timeout_ms)
        request.benchmark_runs = min(request.benchmark_runs, self.settings.simulation_max_benchmark_runs)
        spec = self._parse_index(recommendation.proposed_change)
        query_ids = [int(item["query_id"]) for item in recommendation.affected_queries if "query_id" in item]
        queries = (
            db.query(QueryStatistic)
            .filter(QueryStatistic.query_id.in_(query_ids))
            .order_by(QueryStatistic.total_exec_time_ms.desc())
            .all()
        )
        if not queries:
            raise ValueError("no affected telemetry queries found")

        limitations: list[str] = [
            "Simulation executes only on the isolated sandbox database.",
            "HypoPG changes planner metadata only; it never creates a production index.",
            "Representative parameter values are synthesized for normalized pg_stat_statements queries.",
        ]
        sandbox_tables = set()
        for q in queries:
            shape = parse_query_shape(q.normalized_query)
            for relation in shape.relations:
                if relation != "unknown_relation":
                    sandbox_tables.add(relation)
        sandbox_tables.add(spec.table_name)

        self._reset_sandbox()
        try:
            copied = {}
            for table_name in sorted(sandbox_tables):
                copied[table_name] = self._replicate_table(db, table_name, request.max_rows_per_table)
                if copied[table_name]["truncated"]:
                    limitations.append(f"Table {table_name} was capped at {request.max_rows_per_table:,} rows.")

            extension_version = self._execute_sandbox("SELECT extversion FROM pg_extension WHERE extname='hypopg'").scalar()
            if not extension_version:
                raise RuntimeError("HypoPG is not installed in the sandbox database; recreate the sandbox volume with the v0.6 image")
            self._analyze_all(copied)

            baseline_plans = []
            proposed_plans = []
            differences = []
            affected = []
            baseline_costs = []
            proposed_costs = []
            benchmark_rows = []

            for q in queries:
                sql = self._prepare_query(q.normalized_query, copied)
                baseline = self._explain(sql, request.statement_timeout_ms)
                baseline_cost = self._plan_cost(baseline)
                self._execute_sandbox("SELECT hypopg_reset();")
                hypopg_name = self._create_hypothetical(spec)
                proposed = self._explain(sql, request.statement_timeout_ms)
                proposed_cost = self._plan_cost(proposed)
                baseline_costs.append(baseline_cost)
                proposed_costs.append(proposed_cost)
                baseline_plans.append({"query_id": q.query_id, "plan": baseline})
                proposed_plans.append({"query_id": q.query_id, "plan": proposed, "hypothetical_index": hypopg_name})
                differences.append(self._plan_difference(baseline, proposed))
                affected.append({
                    "query_id": q.query_id,
                    "calls": q.calls,
                    "mean_exec_time_ms": q.mean_exec_time_ms,
                    "query_frequency_per_minute": q.query_frequency_per_minute,
                })
                self._execute_sandbox("SELECT hypopg_reset();")

                if request.benchmark_runs > 0:
                    benchmark_rows.append(self._benchmark_with_real_sandbox_index(
                        sql, spec, request.benchmark_runs, request.statement_timeout_ms
                    ))

            baseline_cost = sum(baseline_costs) / len(baseline_costs)
            proposed_cost = sum(proposed_costs) / len(proposed_costs)
            improvement = ((baseline_cost - proposed_cost) / baseline_cost * 100.0) if baseline_cost > 0 else 0.0
            storage = self._storage_impact(db, spec)
            write = self._write_overhead(db, spec)
            confidence = self._confidence(recommendation.confidence, improvement, differences)
            benchmark = {
                "runs": request.benchmark_runs,
                "queries": benchmark_rows,
                "method": "sandbox-only real index benchmark; hypothetical index is used for plan comparison",
            }
            return {
                "baseline_cost": round(baseline_cost, 3),
                "proposed_cost": round(proposed_cost, 3),
                "improvement": round(improvement, 3),
                "affected_queries": affected,
                "plan_differences": differences,
                "estimated_storage_impact": storage,
                "write_overhead_estimate": write,
                "confidence": confidence,
                "limitations": limitations,
                "benchmark": benchmark,
                "baseline_plans": baseline_plans,
                "proposed_plans": proposed_plans,
                "error": None,
            }
        finally:
            self._reset_sandbox()

    def _reset_sandbox(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))

    def _execute_sandbox(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        with self._engine.begin() as conn:
            return conn.execute(text(sql), params or {})

    def _replicate_table(self, production_db: Session, table_name: str, max_rows: int) -> dict[str, Any]:
        engine = production_db.get_bind()
        inspector = inspect(engine)
        schema = "public"
        columns = inspector.get_columns(table_name, schema=schema)
        if not columns:
            raise ValueError(f"production table not found: {schema}.{table_name}")
        pk = {item["name"] for item in inspector.get_pk_constraint(table_name, schema=schema).get("constrained_columns", [])}
        metadata = MetaData()
        cloned = Table(
            table_name,
            metadata,
            *[
                Column(
                    c["name"],
                    c["type"] if not isinstance(c["type"], NullType) else postgresql.TEXT(),
                    nullable=bool(c.get("nullable", True)),
                    primary_key=c["name"] in pk,
                )
                for c in columns
            ],
            schema="public",
        )
        with self._engine.begin() as sandbox:
            sandbox.execute(text(CreateTable(cloned).compile(dialect=postgresql.dialect())))
            indexes = inspector.get_indexes(table_name, schema=schema)
            for idx in indexes:
                idx_cols = idx.get("column_names") or []
                if not idx_cols or idx.get("duplicates_constraint"):
                    continue
                idx_obj = Index(
                    idx.get("name") or f"dbzenith_{table_name}_{hashlib.sha1(','.join(idx_cols).encode()).hexdigest()[:8]}",
                    *[cloned.c[name] for name in idx_cols if name in cloned.c],
                    unique=bool(idx.get("unique", False)),
                )
                if len(idx_obj.expressions) != len(idx_cols):
                    continue
                sandbox.execute(text(CreateIndex(idx_obj).compile(dialect=postgresql.dialect())))

        prod = production_db.execute(text(f'SELECT * FROM "public"."{table_name}" LIMIT :limit'), {"limit": max_rows + 1}).mappings().all()
        truncated = len(prod) > max_rows
        prod = prod[:max_rows]
        if prod:
            rows = [dict(r) for r in prod]
            sandbox_table = Table(table_name, MetaData(), autoload_with=self._engine, schema="public")
            with self._engine.begin() as sandbox:
                for offset in range(0, len(rows), 1000):
                    sandbox.execute(sandbox_table.insert(), rows[offset:offset + 1000])
        return {"table": table_name, "rows": len(prod), "truncated": truncated}

    def _analyze_all(self, copied: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            for table_name in copied:
                conn.execute(text(f'ANALYZE "public"."{table_name}"'))

    def _parse_index(self, proposed_change: str) -> IndexSpec:
        match = _INDEX_CHANGE.match(proposed_change)
        if not match:
            raise ValueError("proposed change is not a supported CREATE INDEX recommendation")
        index_name = match.group("index")
        schema = match.group("schema")
        table_name = match.group("table").strip('"`')
        columns = match.group("columns")
        if schema and schema != "public":
            raise ValueError("sandbox simulation only permits the public schema")
        if not _IDENTIFIER.match(table_name):
            raise ValueError("invalid table identifier")
        if not columns or any(";" in part for part in columns.split(",")):
            raise ValueError("invalid index columns")
        return IndexSpec("public", table_name, columns.strip(), index_name)

    def _create_hypothetical(self, spec: IndexSpec) -> str:
        sql = "SELECT * FROM hypopg_create_index(:ddl)"
        ddl = f'CREATE INDEX ON "{spec.table_name}" ({spec.columns_sql})'
        row = self._execute_sandbox(sql, {"ddl": ddl}).mappings().first()
        if not row:
            raise RuntimeError("HypoPG did not create a hypothetical index")
        return str(next(iter(row.values())))

    def _explain(self, sql: str, timeout_ms: int) -> dict[str, Any]:
        safe = self._readonly_sql(sql)
        with self._engine.begin() as conn:
            conn.execute(text("SET LOCAL statement_timeout = :timeout"), {"timeout": timeout_ms})
            conn.execute(text("SET LOCAL lock_timeout = :timeout"), {"timeout": min(timeout_ms, 2000)})
            conn.execute(text("SET LOCAL idle_in_transaction_session_timeout = :timeout"), {"timeout": timeout_ms + 1000})
            conn.execute(text("SET LOCAL temp_file_limit = '128MB'"))
            conn.execute(text("SET LOCAL max_parallel_workers_per_gather = 0"))
            result = conn.execute(text(f"EXPLAIN (FORMAT JSON) {safe}")).scalar_one()
            return result[0] if isinstance(result, list) else result

    def _benchmark_with_real_sandbox_index(self, sql: str, spec: IndexSpec, runs: int, timeout_ms: int) -> dict[str, Any]:
        index_name = spec.index_name or f"dbzenith_sim_{hashlib.sha1((spec.table_name + spec.columns_sql).encode()).hexdigest()[:10]}"
        quoted_name = '"' + index_name.replace('"', '""') + '"'
        ddl = f'CREATE INDEX {quoted_name} ON "{spec.table_name}" ({spec.columns_sql})'
        baseline_times = self._benchmark(sql, runs, timeout_ms, drop_cache_hint=False)
        with self._engine.begin() as conn:
            conn.execute(text(ddl))
        try:
            proposed_times = self._benchmark(sql, runs, timeout_ms, drop_cache_hint=False)
            baseline_mean = sum(baseline_times) / len(baseline_times)
            proposed_mean = sum(proposed_times) / len(proposed_times)
            improvement = ((baseline_mean - proposed_mean) / baseline_mean * 100.0) if baseline_mean > 0 else 0.0
            return {
                "index": index_name,
                "runs": runs,
                "baseline_execution_times_ms": baseline_times,
                "proposed_execution_times_ms": proposed_times,
                "baseline_mean_execution_ms": round(baseline_mean, 3),
                "proposed_mean_execution_ms": round(proposed_mean, 3),
                "observed_improvement_percent": round(improvement, 3),
            }
        finally:
            with self._engine.begin() as conn:
                conn.execute(text(f"DROP INDEX IF EXISTS {quoted_name}"))

    def _benchmark(self, sql: str, runs: int, timeout_ms: int, drop_cache_hint: bool = False) -> list[float]:
        safe = self._readonly_sql(sql)
        times = []
        for _ in range(runs):
            with self._engine.begin() as conn:
                conn.execute(text("SET LOCAL statement_timeout = :timeout"), {"timeout": timeout_ms})
                conn.execute(text("SET LOCAL lock_timeout = :timeout"), {"timeout": min(timeout_ms, 2000)})
                conn.execute(text("SET LOCAL temp_file_limit = '128MB'"))
                plan = conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {safe}")).scalar_one()
                payload = plan[0] if isinstance(plan, list) else plan
                times.append(float(payload["Execution Time"]))
        return [round(v, 3) for v in times]

    @staticmethod
    def _readonly_sql(sql: str) -> str:
        stripped = sql.strip().rstrip(";")
        if ";" in stripped:
            raise ValueError("multi-statement queries are strictly prohibited in the sandbox")
        if "--" in stripped or "/*" in stripped:
            raise ValueError("SQL comments are not permitted in simulation queries")
        if not re.match(r"^(SELECT|WITH|VALUES)\b", stripped, re.I):
            raise ValueError("only SELECT/WITH/VALUES statements may be simulated")
        if re.search(r"\b(INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|TRUNCATE|GRANT|REVOKE|COPY|EXECUTE)\b", stripped, re.I):
            raise ValueError("non-read-only SQL is not permitted in the sandbox")
        return stripped

    def _prepare_query(self, sql: str, copied: dict[str, Any]) -> str:
        sql = sql.strip().rstrip(";")
        if "$" not in sql:
            return sql
        shape = parse_query_shape(sql)
        relations = set(shape.relations)
        type_map: dict[tuple[str, str], str] = {}
        with self._engine.connect() as conn:
            for relation in relations:
                rows = conn.execute(text("""
                    SELECT column_name, data_type, udt_name
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=:table
                """), {"table": relation}).mappings().all()
                for r in rows:
                    data_type = r["data_type"] or r["udt_name"]
                    type_map[(relation, r["column_name"])] = data_type
                for alias, relation_name in shape.aliases.items():
                    if relation_name == relation:
                        for r in rows:
                            type_map[(alias, r["column_name"])] = r["data_type"] or r["udt_name"]
        replacements: dict[str, str] = {}
        for m in re.finditer(r"([\w\"]+(?:\.[\w\"]+)?)\s*(?:=|<|>|<=|>=|<>|!=|LIKE|ILIKE|IN)\s*\$(\d+)", sql, re.I):
            col_token, number = m.group(1), m.group(2)
            col = col_token.strip('"').split('.')[-1]
            rel = col_token.strip('"').split('.')[0] if '.' in col_token else (next(iter(relations), ""))
            data_type = type_map.get((rel.strip('"'), col), "text")
            replacements[number] = self._literal_for_type(data_type)
        for number in re.findall(r"\$(\d+)", sql):
            replacements.setdefault(number, "1")
        for number, literal in sorted(replacements.items(), key=lambda x: int(x[0]), reverse=True):
            sql = sql.replace(f"${number}", literal)
        return sql

    @staticmethod
    def _literal_for_type(data_type: str) -> str:
        t = data_type.lower()
        if any(x in t for x in ("int", "numeric", "decimal", "real", "double", "serial")):
            return "1"
        if t in {"boolean"}:
            return "true"
        if t == "date":
            return "CURRENT_DATE"
        if "timestamp" in t or t == "time without time zone" or t == "time with time zone":
            return "CURRENT_TIMESTAMP"
        if t == "uuid":
            return "'00000000-0000-0000-0000-000000000001'::uuid"
        return "'dbzenith'"

    @staticmethod
    def _plan_cost(plan: dict[str, Any]) -> float:
        return float(plan.get("Plan", {}).get("Total Cost", 0.0))

    @staticmethod
    def _plan_difference(baseline: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
        b = baseline.get("Plan", {})
        p = proposed.get("Plan", {})

        def flatten(node: dict[str, Any]) -> list[dict[str, Any]]:
            items = [{
                "node_type": node.get("Node Type"),
                "relation": node.get("Relation Name"),
                "index": node.get("Index Name"),
            }]
            for child in node.get("Plans", []) or []:
                items.extend(flatten(child))
            return items

        baseline_nodes = flatten(b)
        proposed_nodes = flatten(p)
        return {
            "baseline_node": b.get("Node Type"),
            "proposed_node": p.get("Node Type"),
            "baseline_relation": b.get("Relation Name"),
            "proposed_relation": p.get("Relation Name"),
            "baseline_total_cost": b.get("Total Cost"),
            "proposed_total_cost": p.get("Total Cost"),
            "node_changed": b.get("Node Type") != p.get("Node Type") or baseline_nodes != proposed_nodes,
            "index_used": any(n.get("node_type") in {"Index Scan", "Index Only Scan", "Bitmap Heap Scan", "Bitmap Index Scan"} for n in proposed_nodes),
            "baseline_nodes": baseline_nodes,
            "proposed_nodes": proposed_nodes,
        }

    def _storage_impact(self, production_db: Session, spec: IndexSpec) -> dict[str, Any]:
        row = production_db.execute(text("""
            SELECT pg_total_relation_size(c.oid) AS table_bytes,
                   COALESCE(pg_indexes_size(c.oid), 0) AS index_bytes
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=:schema AND c.relname=:table
        """), {"schema": spec.table_schema, "table": spec.table_name}).mappings().first()
        table_bytes = int(row["table_bytes"] or 0) if row else 0
        index_bytes = int(row["index_bytes"] or 0) if row else 0
        # PostgreSQL has no cheap exact size for a hypothetical index. Report a bounded estimate.
        return {
            "table_size_bytes": table_bytes,
            "current_index_bytes": index_bytes,
            "estimated_new_index_bytes": None,
            "method": "exact size unavailable for HypoPG; use sandbox benchmark or pg_relation_size after a real index is created",
        }

    def _write_overhead(self, production_db: Session, spec: IndexSpec) -> dict[str, Any]:
        row = production_db.execute(text("""
            SELECT COALESCE(s.n_tup_ins,0)+COALESCE(s.n_tup_upd,0)+COALESCE(s.n_tup_del,0) AS writes
            FROM pg_stat_user_tables s WHERE s.schemaname=:schema AND s.relname=:table
        """), {"schema": spec.table_schema, "table": spec.table_name}).mappings().first()
        writes = int(row["writes"] or 0) if row else 0
        return {
            "classification": "additional index maintenance on INSERT/UPDATE/DELETE",
            "observed_table_writes": writes,
            "estimated_relative_overhead": "low" if writes < 10000 else "moderate" if writes < 100000 else "high",
            "method": "workload-write activity classification; exact per-index write CPU is not observable before creation",
        }

    @staticmethod
    def _confidence(recommendation_confidence: float, improvement: float, differences: list[dict[str, Any]]) -> float:
        plan_changed = any(d.get("node_changed") or d.get("index_used") for d in differences)
        score = recommendation_confidence * 0.65
        score += min(0.25, max(0.0, improvement) / 100.0 * 0.25)
        if plan_changed:
            score += 0.10
        return round(min(0.99, max(0.05, score)), 3)
