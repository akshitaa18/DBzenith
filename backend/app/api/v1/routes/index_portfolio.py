"""API routes for PostgreSQL Index Portfolio Advisor (Phase 8 Feature A)."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_analyst, require_viewer
from app.core.security import TokenPayload
from app.db.session import get_db
from app.models.security import SecurityAuditEvent
from app.services.recommendations.engine import RecommendationEngine
from app.services.recommendations.index_portfolio import IndexPortfolioAdvisor

router = APIRouter(prefix="/index-portfolio", tags=["index-portfolio"])


class PortfolioAnalyzeRequest(BaseModel):
    schema_name: str | None = None
    table_name: str | None = None
    category: str | None = None
    access_method: str | None = None
    search: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=200)
    min_stats_age_seconds: int = Field(default=86400, ge=0)
    low_usage_scan_threshold: int = Field(default=5, ge=0)
    sync_recommendations: bool = False
    catalog_override: list[dict[str, Any]] | None = None
    column_stats_override: dict[str, dict[str, Any]] | None = None
    stats_reset_at: datetime | None = None
    stats_reset_supplied: bool = False
    workload_queries_override: list[dict[str, Any]] | None = None


@router.get("")
def get_index_portfolio(
    schema_name: str | None = Query(None),
    table_name: str | None = Query(None),
    category: str | None = Query(None, description="Filter by: all, overlapping, low_usage, healthy, unsupported_type"),
    access_method: str | None = Query(None, description="Filter by: btree, gin, gist, brin, hash"),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    min_stats_age_seconds: int = Query(86400, ge=0),
    low_usage_scan_threshold: int = Query(5, ge=0),
    db: Session = Depends(get_db),
    _user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    """Performs read-only PostgreSQL index portfolio analysis without modifying any database state."""
    advisor = IndexPortfolioAdvisor(
        min_stats_age_seconds=min_stats_age_seconds,
        low_usage_scan_threshold=low_usage_scan_threshold,
    )
    return advisor.analyze_portfolio(
        db,
        schema_filter=schema_name,
        table_filter=table_name,
        category_filter=category,
        access_method_filter=access_method,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.post("/analyze")
def analyze_index_portfolio(
    payload: PortfolioAnalyzeRequest,
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_viewer),
) -> dict[str, Any]:
    """Runs index portfolio analysis with optional schema overrides or recommendation lifecycle sync."""
    if payload.sync_recommendations and user.role.upper() not in ("ANALYST", "DBA", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ANALYST, DBA, or ADMIN role is required to sync portfolio candidates into recommendations.",
        )

    col_stats_tuple_map: dict[tuple[str, str], dict[str, Any]] | None = None
    if payload.column_stats_override is not None:
        col_stats_tuple_map = {}
        for k, v in payload.column_stats_override.items():
            if "." in k:
                t, c = k.split(".", 1)
                col_stats_tuple_map[(t.lower(), c.lower())] = v

    advisor = IndexPortfolioAdvisor(
        min_stats_age_seconds=payload.min_stats_age_seconds,
        low_usage_scan_threshold=payload.low_usage_scan_threshold,
    )
    report = advisor.analyze_portfolio(
        db,
        schema_filter=payload.schema_name,
        table_filter=payload.table_name,
        category_filter=payload.category,
        access_method_filter=payload.access_method,
        search=payload.search,
        page=payload.page,
        page_size=payload.page_size,
        catalog_override=payload.catalog_override,
        column_stats_override=col_stats_tuple_map,
        stats_reset_override=payload.stats_reset_at,
        stats_reset_supplied=payload.stats_reset_supplied or (payload.stats_reset_at is not None),
        workload_queries_override=payload.workload_queries_override,
    )

    if payload.sync_recommendations:
        recs = RecommendationEngine().generate(db, limit=100)
        report["synced_recommendations_count"] = len(recs)
        db.add(
            SecurityAuditEvent(
                event_category="RECOMMENDATION",
                action="index_portfolio_synced",
                actor_id=str(user.user_id),
                actor_username=user.username,
                actor_role=user.role,
                target_entity="index_portfolio",
                target_id="portfolio",
                status="SUCCESS",
                details_json=json.dumps(
                    {
                        "overlapping_candidates": report["summary"]["overlapping_candidates_count"],
                        "missing_proposals": report["summary"]["missing_or_composite_proposals_count"],
                        "synced_recommendations_count": len(recs),
                    }
                ),
            )
        )
        db.commit()

    return report


@router.get("/export")
def export_index_portfolio(
    format: str = Query("json", pattern="^(json|csv)$"),
    schema_name: str | None = Query(None),
    table_name: str | None = Query(None),
    category: str | None = Query(None),
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_analyst),
) -> Response:
    """Exports the read-only index portfolio inventory and advisor candidates (ANALYST+ required)."""
    advisor = IndexPortfolioAdvisor()
    report = advisor.analyze_portfolio(
        db,
        schema_filter=schema_name,
        table_filter=table_name,
        category_filter=category,
        page=1,
        page_size=200,
    )

    db.add(
        SecurityAuditEvent(
            event_category="AUDIT",
            action="index_portfolio_exported",
            actor_id=str(user.user_id),
            actor_username=user.username,
            actor_role=user.role,
            target_entity="index_portfolio",
            target_id=format,
            status="SUCCESS",
            details_json=json.dumps(
                {
                    "format": format,
                    "total_indexes": report["summary"]["total_indexes"],
                    "overlapping_candidates": report["summary"]["overlapping_candidates_count"],
                    "low_usage_candidates": report["summary"]["low_usage_candidates_count"],
                }
            ),
        )
    )
    db.commit()

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "schema_name",
                "table_name",
                "index_name",
                "access_method",
                "columns",
                "is_primary",
                "is_unique",
                "index_size_bytes",
                "idx_scan",
                "category",
                "statistics_status",
                "write_overhead_level",
                "requires_dba_review",
            ]
        )
        for item in report["inventory"]["items"]:
            writer.writerow(
                [
                    item["schema_name"],
                    item["table_name"],
                    item["index_name"],
                    item["access_method"],
                    ",".join(item.get("columns", [])),
                    item.get("is_primary", False),
                    item.get("is_unique", False),
                    item.get("index_size_bytes", 0),
                    item.get("idx_scan", ""),
                    item.get("category", ""),
                    item.get("statistics_status", ""),
                    (item.get("write_overhead") or {}).get("level", ""),
                    item.get("requires_dba_review", False),
                ]
            )
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="dbzenith_index_portfolio.csv"'},
        )

    return Response(
        content=json.dumps(report, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="dbzenith_index_portfolio.json"'},
    )
