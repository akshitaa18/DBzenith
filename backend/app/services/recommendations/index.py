from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.workload import QueryStatistic
from app.services.recommendations.base import Recommendation
from app.services.recommendations.parsing import parse_query_shape


class IndexAdvisor:
    """Deterministic index analysis; it never executes DDL."""

    def advise(self, db: Session, limit: int = 100) -> list[Recommendation]:
        queries = (
            db.query(QueryStatistic)
            .order_by(QueryStatistic.total_exec_time_ms.desc())
            .limit(limit)
            .all()
        )
        if not queries:
            return []
        indexes = self._indexes(db)
        recommendations: list[Recommendation] = []
        recommendations.extend(self._redundant_index_recommendations(indexes))
        for q in queries:
            if not q.normalized_query.strip().lower().startswith(("select", "with")):
                continue
            shape = parse_query_shape(q.normalized_query)
            existing = indexes
            for relation, column in shape.where_columns + shape.join_columns:
                if not relation or relation == "unknown_relation":
                    continue
                if self._covered(existing, relation, column):
                    continue
                score = self._confidence(q, column)
                kind = "index_where" if (relation, column) in shape.where_columns else "index_join"
                rec = self._recommendation(
                    kind, relation, [column], q, score,
                    reason=f"The workload repeatedly uses {relation}.{column} in a predicate/join and no existing index begins with that column.",
                    change=f"CREATE INDEX CONCURRENTLY ON {relation} ({column});",
                    benefit="Can reduce heap/index work for selective predicates or join probes.",
                    risk="Adds write amplification and consumes storage; validate selectivity and write workload before approval.",
                )
                recommendations.append(rec)

            for relation, column, direction in shape.order_columns:
                if relation == "unknown_relation" or self._covered(existing, relation, column):
                    continue
                recommendations.append(self._recommendation(
                    "index_order_by", relation, [column], q, self._confidence(q, column),
                    reason=f"The query orders by {relation}.{column} and an existing index does not provide the leading order key.",
                    change=f"CREATE INDEX CONCURRENTLY ON {relation} ({column} {direction});",
                    benefit="May avoid or reduce an explicit sort for repeated ordered access.",
                    risk="Additional index storage and write maintenance; planner may still prefer a sort.",
                ))

            if shape.group_columns and shape.relations:
                cols = shape.group_columns[:3]
                relation = shape.relations[0]
                if not self._covered_prefix(existing, relation, cols):
                    recommendations.append(self._recommendation(
                        "composite_index", relation, cols, q, min(0.95, self._confidence(q, cols[0]) + 0.05),
                        reason="GROUP BY columns recur in a costly workload query and no existing composite index matches the leading grouping columns.",
                        change=f"CREATE INDEX CONCURRENTLY ON {relation} ({', '.join(cols)});",
                        benefit="May reduce grouping/sorting work when the access path is selective and the key order matches the query.",
                        risk="Composite indexes increase write and storage cost; key order matters and redundant indexes should be avoided.",
                    ))
        return self._dedupe(recommendations)

    @staticmethod
    def _indexes(db: Session) -> list[dict[str, Any]]:
        if db.bind and db.bind.dialect.name != "postgresql":
            return []
        try:
            rows = db.execute(text("""
                SELECT i.schemaname, i.tablename, i.indexname, i.indexdef,
                       ix.indisunique AS is_unique, ix.indisprimary AS is_primary
                FROM pg_indexes i
                JOIN pg_class c ON c.relname = i.indexname
                JOIN pg_index ix ON ix.indexrelid = c.oid
                JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = i.schemaname
                WHERE i.schemaname NOT IN ('pg_catalog', 'information_schema')
            """)).mappings().all()
        except Exception:
            return []
        result = []
        for r in rows:
            cols = re.findall(r"\((.*?)\)", r["indexdef"] or "")
            columns = []
            if cols:
                columns = [re.sub(r"\s+(ASC|DESC|NULLS\s+(FIRST|LAST))\b", "", c.strip(), flags=re.I).strip('"') for c in cols[-1].split(',')]
            result.append({**dict(r), "columns": columns, "is_unique": bool(r.get("is_unique", False)), "is_primary": bool(r.get("is_primary", False))})
        return result

    @staticmethod
    def _covered(indexes: list[dict[str, Any]], relation: str, column: str) -> bool:
        c = column.lower()
        return any(i["tablename"].lower() == relation.lower() and i["columns"] and i["columns"][0].lower() == c for i in indexes)

    @staticmethod
    def _covered_prefix(indexes: list[dict[str, Any]], relation: str, columns: list[str]) -> bool:
        wanted = [c.lower() for c in columns]
        return any(i["tablename"].lower() == relation.lower() and [c.lower() for c in i["columns"][:len(wanted)]] == wanted for i in indexes)

    @staticmethod
    def _confidence(q: QueryStatistic, column: str) -> float:
        frequency = min(1.0, max(0.0, q.query_frequency_per_minute / 60.0))
        cost = min(1.0, max(0.0, q.total_exec_time_ms / 1000.0))
        reads = min(1.0, max(0.0, q.shared_blks_read / 1000.0))
        return round(min(0.98, 0.45 + 0.25 * frequency + 0.20 * cost + 0.10 * reads), 3)

    @staticmethod
    def _recommendation(kind: str, relation: str, columns: list[str], q: QueryStatistic, confidence: float, *, reason: str, change: str, benefit: str, risk: str) -> Recommendation:
        affected = [{"query_id": q.query_id, "mean_exec_time_ms": round(q.mean_exec_time_ms, 3), "calls": q.calls, "frequency_per_minute": round(q.query_frequency_per_minute, 3)}]
        raw_key = f"{kind}|{relation}|{','.join(columns)}|{change}"
        key = hashlib.sha256(raw_key.encode()).hexdigest()
        return Recommendation(key, kind, relation, change, reason,
            {"query_id": q.query_id, "mean_exec_time_ms": q.mean_exec_time_ms, "total_exec_time_ms": q.total_exec_time_ms, "calls": q.calls, "query_frequency_per_minute": q.query_frequency_per_minute, "shared_blks_read": q.shared_blks_read, "columns": columns},
            benefit, risk, confidence, affected, True)

    @staticmethod
    def _redundant_index_recommendations(indexes: list[dict[str, Any]]) -> list[Recommendation]:
        out: list[Recommendation] = []
        for candidate in indexes:
            if candidate.get("is_primary") or candidate.get("is_unique") or len(candidate.get("columns", [])) != 1:
                continue
            ccol = candidate["columns"][0].lower()
            for broader in indexes:
                if broader is candidate or broader.get("tablename", "").lower() != candidate.get("tablename", "").lower():
                    continue
                bcols = [c.lower() for c in broader.get("columns", [])]
                if len(bcols) > 1 and bcols[0] == ccol and not broader.get("is_primary"):
                    key = hashlib.sha256(f"redundant-index|{candidate['schemaname']}|{candidate['indexname']}|{broader['indexname']}".encode()).hexdigest()
                    out.append(Recommendation(
                        key, "redundant_index", candidate["indexname"],
                        f"Evaluate dropping {candidate['indexname']} because {broader['indexname']} has the same leading key ({candidate['columns'][0]}) and is wider.",
                        "A single-column index is a left-prefix duplicate of an existing composite index.",
                        {"candidate_index": candidate["indexname"], "covering_index": broader["indexname"], "candidate_columns": candidate["columns"], "covering_columns": broader["columns"]},
                        "Potentially reduces index storage and write maintenance if no query depends on the narrower index for ordering or uniqueness.",
                        "Dropping an index can regress queries; validate usage and constraints before approval.", 0.70, [], True
                    ))
                    break
        return out

    @staticmethod
    def _dedupe(items: list[Recommendation]) -> list[Recommendation]:
        seen: dict[str, Recommendation] = {}
        out: list[Recommendation] = []
        for item in items:
            if item.key not in seen:
                seen[item.key] = item
                out.append(item)
            else:
                existing = seen[item.key]
                existing_qids = {q.get("query_id") for q in existing.affected_queries if isinstance(q, dict)}
                for q in item.affected_queries:
                    if isinstance(q, dict) and q.get("query_id") not in existing_qids:
                        existing.affected_queries.append(q)
                        existing_qids.add(q.get("query_id"))
        return out
