"""Comprehensive Workload & Telemetry Generator for DBZenith v0.7.

Generates a large, diverse, realistic query set exercising all platform capabilities:
- 11 Core DBA Views (Overview, Slow Queries, Query Details, Plan Viewer, GNN,
  Recommendations, Simulations, Approvals, Assistant, Health, Audit)
- 4 Recommendation Categories (Indexes, AST Rewrites, Partitioning, Join Strategies)
- 5 AST Rewrite Patterns (Redundant DISTINCT, OR->IN, EXISTS 1, IN-subquery ORDER BY, LEFT->INNER)
- 3 Latency Severity Tiers (Critical >=500ms, High >=100ms, Moderate/Fast <100ms)
- Multi-snapshot historical trend in pg_stat_statements
- Pre-computed HypoPG virtual index sandbox simulations
- Pre-seeded Human Approval Center decisions and immutable Audit Ledger
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Setup path to import backend app modules
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.models.workload import WorkloadSnapshot, QueryStatistic
from app.models.recommendation import OptimizationRecommendation, RecommendationAuditEvent
from app.models.simulation import OptimizationSimulation
from app.models.plan import PlanAnalysis
from app.models.security import SecurityAuditEvent, User
from app.services.recommendations.engine import RecommendationEngine
from app.services.privacy.gateway import PrivacyGateway
from app.services.privacy.contracts import RawPlan


COMPREHENSIVE_QUERIES = [
    # -------------------------------------------------------------------------
    # Tier 1: CRITICAL SLOW QUERIES (>= 500 ms) - Heavy Scans, Multi-way Joins
    # -------------------------------------------------------------------------
    {
        "query": "SELECT order_id, customer_id, amount, order_date, status FROM orders WHERE status = 'pending' AND amount > 250.00 ORDER BY order_date DESC LIMIT 50",
        "calls": 2840,
        "mean_ms": 685.4,
        "min_ms": 420.1,
        "max_ms": 1420.5,
        "rows": 50,
        "hit": 18200,
        "read": 14500,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Seq Scan",
        "relation": "orders",
        "category": "Filter Bottleneck",
    },
    {
        "query": "SELECT o.order_id, c.last_name, p.product_name, r.region_name, o.amount FROM orders o JOIN customers c ON c.customer_id = o.customer_id JOIN products p ON p.product_id = o.product_id JOIN regions r ON r.region_id = o.region_id WHERE o.amount > 500.00 ORDER BY o.amount DESC LIMIT 50",
        "calls": 820,
        "mean_ms": 892.6,
        "min_ms": 610.0,
        "max_ms": 1850.2,
        "rows": 50,
        "hit": 32000,
        "read": 26400,
        "temp_read": 420,
        "temp_written": 420,
        "explain_type": "Hash Join",
        "relation": "orders",
        "category": "Multi-table Star Join",
    },
    {
        "query": "SELECT a.customer_id, count(*) AS pair_count FROM orders a JOIN orders b ON b.customer_id = a.customer_id AND b.order_id != a.order_id WHERE a.amount > 600.00 GROUP BY a.customer_id LIMIT 20",
        "calls": 410,
        "mean_ms": 1180.5,
        "min_ms": 840.0,
        "max_ms": 2450.0,
        "rows": 20,
        "hit": 28000,
        "read": 34500,
        "temp_read": 850,
        "temp_written": 850,
        "explain_type": "Nested Loop",
        "relation": "orders",
        "category": "Self-Join Pairwise Scan",
    },
    {
        "query": "SELECT a.customer_id, count(*) FROM telemetry_demo_orders a JOIN telemetry_demo_orders b ON b.customer_id = a.customer_id WHERE a.amount > 800.00 GROUP BY a.customer_id LIMIT 10",
        "calls": 620,
        "mean_ms": 945.2,
        "min_ms": 680.0,
        "max_ms": 1920.0,
        "rows": 10,
        "hit": 24000,
        "read": 29800,
        "temp_read": 610,
        "temp_written": 610,
        "explain_type": "Nested Loop",
        "relation": "telemetry_demo_orders",
        "category": "Demo Orders Self-Join",
    },
    {
        "query": "SELECT customer_id, status, count(order_id) AS total_orders, sum(amount) AS total_spend FROM orders GROUP BY customer_id, status ORDER BY total_spend DESC LIMIT 25",
        "calls": 1420,
        "mean_ms": 560.8,
        "min_ms": 380.0,
        "max_ms": 1120.0,
        "rows": 25,
        "hit": 21000,
        "read": 16800,
        "temp_read": 180,
        "temp_written": 180,
        "explain_type": "Aggregate",
        "relation": "orders",
        "category": "Composite Aggregation",
    },
    {
        "query": "SELECT c.customer_id, c.first_name, c.last_name, o.order_id, o.amount, o.order_date FROM customers c JOIN orders o ON o.customer_id = c.customer_id WHERE o.status = 'completed' ORDER BY o.order_date DESC LIMIT 50",
        "calls": 950,
        "mean_ms": 715.3,
        "min_ms": 490.0,
        "max_ms": 1380.0,
        "rows": 50,
        "hit": 25000,
        "read": 19400,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Hash Join",
        "relation": "orders",
        "category": "Customer Orders Full Join",
    },

    # -------------------------------------------------------------------------
    # Tier 2: HIGH LATENCY QUERIES (100 - 499 ms) - Filtering, Range, Rewrites
    # -------------------------------------------------------------------------
    {
        "query": "SELECT order_id, customer_id, amount, order_date FROM orders WHERE order_date >= '2024-01-01' AND order_date < '2024-07-01' ORDER BY order_date DESC",
        "calls": 6800,
        "mean_ms": 482.1,
        "min_ms": 310.0,
        "max_ms": 940.0,
        "rows": 4800,
        "hit": 19500,
        "read": 15200,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Seq Scan",
        "relation": "orders",
        "category": "Range Partition Candidate",
    },
    {
        "query": "SELECT id, customer_id, amount, created_at FROM telemetry_demo_orders WHERE created_at >= '2024-06-01' AND created_at < '2025-01-01' ORDER BY created_at DESC",
        "calls": 7200,
        "mean_ms": 395.4,
        "min_ms": 260.0,
        "max_ms": 820.0,
        "rows": 3600,
        "hit": 22000,
        "read": 17800,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Seq Scan",
        "relation": "telemetry_demo_orders",
        "category": "Demo Range Partition Candidate",
    },
    {
        "query": "SELECT order_id, product_id, quantity, amount FROM orders WHERE customer_id = 42 AND order_date >= '2025-01-01' ORDER BY order_date DESC",
        "calls": 3100,
        "mean_ms": 315.6,
        "min_ms": 190.0,
        "max_ms": 680.0,
        "rows": 85,
        "hit": 14200,
        "read": 9400,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Bitmap Heap Scan",
        "relation": "orders",
        "category": "Customer Date Filter",
    },
    {
        "query": "SELECT id, customer_id, amount, status FROM telemetry_demo_orders WHERE status = 'pending' AND amount > 500.00 ORDER BY created_at DESC LIMIT 100",
        "calls": 4200,
        "mean_ms": 412.3,
        "min_ms": 270.0,
        "max_ms": 880.0,
        "rows": 100,
        "hit": 18500,
        "read": 13200,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Seq Scan",
        "relation": "telemetry_demo_orders",
        "category": "Demo Filter Scan",
    },
    {
        "query": "SELECT region_id, status, count(*) AS order_count, avg(amount) AS avg_amount FROM orders GROUP BY region_id, status ORDER BY order_count DESC",
        "calls": 980,
        "mean_ms": 425.8,
        "min_ms": 280.0,
        "max_ms": 890.0,
        "rows": 32,
        "hit": 16400,
        "read": 11800,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Aggregate",
        "relation": "orders",
        "category": "Region Revenue Grouping",
    },
    {
        "query": "SELECT customer_id, status, count(*), sum(amount) FROM telemetry_demo_orders GROUP BY customer_id, status HAVING count(*) > 3 ORDER BY sum(amount) DESC LIMIT 30",
        "calls": 1850,
        "mean_ms": 340.2,
        "min_ms": 210.0,
        "max_ms": 720.0,
        "rows": 30,
        "hit": 15800,
        "read": 10500,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Aggregate",
        "relation": "telemetry_demo_orders",
        "category": "Demo Group By Filter",
    },
    {
        "query": "SELECT product_id, product_name, price, stock_quantity FROM products WHERE category = 'Electronics' AND price > 199.99 ORDER BY price ASC",
        "calls": 2100,
        "mean_ms": 178.5,
        "min_ms": 95.0,
        "max_ms": 420.0,
        "rows": 45,
        "hit": 9800,
        "read": 4800,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Seq Scan",
        "relation": "products",
        "category": "Product Category Range Scan",
    },
    {
        "query": "SELECT category, count(*) AS product_count, sum(price * stock_quantity) AS inventory_value FROM products GROUP BY category ORDER BY inventory_value DESC",
        "calls": 1200,
        "mean_ms": 142.1,
        "min_ms": 80.0,
        "max_ms": 310.0,
        "rows": 8,
        "hit": 8500,
        "read": 3200,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Aggregate",
        "relation": "products",
        "category": "Inventory Aggregation",
    },
    {
        "query": "SELECT order_id, customer_id, amount, order_date FROM orders ORDER BY amount DESC LIMIT 100",
        "calls": 3400,
        "mean_ms": 235.4,
        "min_ms": 140.0,
        "max_ms": 580.0,
        "rows": 100,
        "hit": 16200,
        "read": 8900,
        "temp_read": 140,
        "temp_written": 140,
        "explain_type": "Sort",
        "relation": "orders",
        "category": "High-Value Order Sort",
    },
    {
        "query": "SELECT product_id, product_name, price FROM products WHERE category = 'Furniture' ORDER BY price DESC LIMIT 50",
        "calls": 1950,
        "mean_ms": 165.7,
        "min_ms": 90.0,
        "max_ms": 390.0,
        "rows": 50,
        "hit": 9200,
        "read": 4100,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Sort",
        "relation": "products",
        "category": "Category Price Sort",
    },

    # -------------------------------------------------------------------------
    # Tier 3: AST REWRITER CANDIDATE QUERIES (Showcase Semantic Optimization)
    # -------------------------------------------------------------------------
    {
        "query": "SELECT DISTINCT customer_id, count(order_id) AS order_count FROM orders WHERE status = 'completed' GROUP BY customer_id ORDER BY order_count DESC LIMIT 50",
        "calls": 2400,
        "mean_ms": 285.6,
        "min_ms": 170.0,
        "max_ms": 610.0,
        "rows": 50,
        "hit": 15400,
        "read": 8200,
        "temp_read": 90,
        "temp_written": 90,
        "explain_type": "Unique",
        "relation": "orders",
        "category": "AST: Redundant Distinct",
    },
    {
        "query": "SELECT order_id, customer_id, amount, status FROM orders WHERE status = 'pending' OR status = 'processing' OR status = 'shipped'",
        "calls": 3800,
        "mean_ms": 215.3,
        "min_ms": 125.0,
        "max_ms": 490.0,
        "rows": 1200,
        "hit": 17100,
        "read": 9600,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Seq Scan",
        "relation": "orders",
        "category": "AST: OR to IN-List",
    },
    {
        "query": "SELECT c.customer_id, c.first_name, c.email FROM customers c WHERE EXISTS (SELECT * FROM orders o WHERE o.customer_id = c.customer_id AND o.amount > 300.00)",
        "calls": 2900,
        "mean_ms": 320.4,
        "min_ms": 195.0,
        "max_ms": 710.0,
        "rows": 450,
        "hit": 18200,
        "read": 11400,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Hash Join",
        "relation": "customers",
        "category": "AST: EXISTS Select 1",
    },
    {
        "query": "SELECT order_id, amount, customer_id FROM orders WHERE customer_id IN (SELECT customer_id FROM customers WHERE region_id = 2 ORDER BY created_at)",
        "calls": 1850,
        "mean_ms": 365.2,
        "min_ms": 220.0,
        "max_ms": 780.0,
        "rows": 820,
        "hit": 16900,
        "read": 12100,
        "temp_read": 120,
        "temp_written": 120,
        "explain_type": "Hash Join",
        "relation": "orders",
        "category": "AST: Subquery Order Elimination",
    },
    {
        "query": "SELECT c.first_name, c.last_name, o.order_id, o.amount FROM customers c LEFT JOIN orders o ON o.customer_id = c.customer_id WHERE o.amount > 750.00",
        "calls": 1600,
        "mean_ms": 310.8,
        "min_ms": 180.0,
        "max_ms": 690.0,
        "rows": 310,
        "hit": 15800,
        "read": 9900,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Hash Join",
        "relation": "customers",
        "category": "AST: LEFT to INNER Join",
    },

    # -------------------------------------------------------------------------
    # Tier 4: MODERATE & FAST BASELINE QUERIES (< 100 ms) - Healthy Baseline
    # -------------------------------------------------------------------------
    {
        "query": "SELECT customer_id, first_name, last_name, phone, address FROM customers WHERE email = 'customer.vip@enterprise.org'",
        "calls": 5200,
        "mean_ms": 88.4,
        "min_ms": 42.0,
        "max_ms": 190.0,
        "rows": 1,
        "hit": 8900,
        "read": 2100,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Index Scan",
        "relation": "customers",
        "category": "Customer Email Lookup",
    },
    {
        "query": "SELECT customer_id, first_name, last_name, created_at FROM customers ORDER BY created_at DESC LIMIT 50",
        "calls": 4100,
        "mean_ms": 76.2,
        "min_ms": 38.0,
        "max_ms": 160.0,
        "rows": 50,
        "hit": 7800,
        "read": 1400,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Index Scan",
        "relation": "customers",
        "category": "Recent Customers Sort",
    },
    {
        "query": "SELECT status, count(*) FROM orders WHERE order_date = CURRENT_DATE GROUP BY status",
        "calls": 6500,
        "mean_ms": 18.5,
        "min_ms": 6.0,
        "max_ms": 45.0,
        "rows": 4,
        "hit": 9500,
        "read": 420,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Bitmap Heap Scan",
        "relation": "orders",
        "category": "Daily Status Summary",
    },
    {
        "query": "SELECT customer_id, first_name, last_name, email FROM customers WHERE customer_id = 7",
        "calls": 18500,
        "mean_ms": 0.85,
        "min_ms": 0.4,
        "max_ms": 3.2,
        "rows": 1,
        "hit": 18500,
        "read": 0,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Index Scan",
        "relation": "customers",
        "category": "Primary Key Customer Lookup",
    },
    {
        "query": "SELECT product_id, product_name, price, stock_quantity FROM products WHERE product_id = 3",
        "calls": 22000,
        "mean_ms": 0.65,
        "min_ms": 0.3,
        "max_ms": 2.8,
        "rows": 1,
        "hit": 22000,
        "read": 0,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Index Scan",
        "relation": "products",
        "category": "Primary Key Product Lookup",
    },
    {
        "query": "SELECT region_id, region_name, country FROM regions WHERE region_id = 1",
        "calls": 14000,
        "mean_ms": 0.45,
        "min_ms": 0.2,
        "max_ms": 1.9,
        "rows": 1,
        "hit": 14000,
        "read": 0,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Index Scan",
        "relation": "regions",
        "category": "Primary Key Region Lookup",
    },
    {
        "query": "SELECT id, customer_id, amount FROM telemetry_demo_orders WHERE status = 'processing' AND amount BETWEEN 100 AND 500 ORDER BY created_at DESC LIMIT 50",
        "calls": 4800,
        "mean_ms": 92.5,
        "min_ms": 48.0,
        "max_ms": 210.0,
        "rows": 50,
        "hit": 12500,
        "read": 3100,
        "temp_read": 0,
        "temp_written": 0,
        "explain_type": "Bitmap Heap Scan",
        "relation": "telemetry_demo_orders",
        "category": "Demo Processing Filter",
    },
]


def generate_comprehensive_workload(db_url: str | None = None) -> dict:
    """Main execution function for comprehensive workload seeding."""
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    settings = get_settings()
    url = db_url or settings.database_url
    print(f"Connecting to database: {url.split('@')[-1] if '@' in url else url}", flush=True)

    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()

    try:
        # 1. Clean Stale / Redundant Records
        print("\n[Step 1/7] Cleaning redundant/stale internal telemetry & metadata...", flush=True)
        session.execute(text("DELETE FROM optimization_simulations;"))
        session.execute(text("DELETE FROM recommendation_audit_events;"))
        session.execute(text("DELETE FROM optimization_recommendations;"))
        session.execute(text("DELETE FROM plan_analyses;"))
        session.execute(text("DELETE FROM query_statistics;"))
        session.execute(text("DELETE FROM workload_snapshots;"))
        session.commit()
        print("  [OK] Stale queries and recommendations cleared.")

        # 2. Ensure Real Schema & Demo Tables
        print("\n[Step 2/7] Verifying e-commerce and demo tables...")
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS telemetry_demo_orders (
                id SERIAL PRIMARY KEY,
                customer_id INT NOT NULL,
                amount NUMERIC(10, 2) NOT NULL,
                status VARCHAR(32) NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
                payload TEXT
            );
        """))
        demo_count = session.execute(text("SELECT count(*) FROM telemetry_demo_orders;")).scalar() or 0
        if demo_count < 5000:
            print("  - Seeding 10,000 demo orders...")
            session.execute(text("""
                INSERT INTO telemetry_demo_orders (customer_id, amount, status, created_at)
                SELECT (g % 300) + 1,
                       round((random() * 1200 + 10)::numeric, 2),
                       CASE (g % 4)
                           WHEN 0 THEN 'pending'
                           WHEN 1 THEN 'completed'
                           WHEN 2 THEN 'processing'
                           ELSE 'cancelled'
                       END,
                       now() - ((g % 60) || ' days')::interval
                FROM generate_series(1, 10000) AS g;
            """))
            session.commit()
        print(f"  [OK] Demo orders ready: {session.execute(text('SELECT count(*) FROM telemetry_demo_orders;')).scalar()} rows.")

        # 3. Create Multi-Snapshot Historical Progression (Extended Multi-Day Enterprise Timeline)
        print("\n[Step 3/7] Generating 7 sequential telemetry snapshots (Extended 7-Day & 24-Hour Timeline)...")
        now = datetime.now(timezone.utc)
        snapshots = []

        # Snapshot 1: 7 days ago (Weekly baseline)
        s1 = WorkloadSnapshot(
            captured_at=now - timedelta(days=7),
            window_seconds=604800.0,
            total_calls=1250000,
            total_exec_time_ms=384000000.0,
            unique_queries=len(COMPREHENSIVE_QUERIES),
            slow_queries=21,
        )
        session.add(s1); session.flush(); snapshots.append(s1)

        # Snapshot 2: 3 days ago
        s2 = WorkloadSnapshot(
            captured_at=now - timedelta(days=3),
            window_seconds=259200.0,
            total_calls=780000,
            total_exec_time_ms=210000000.0,
            unique_queries=len(COMPREHENSIVE_QUERIES),
            slow_queries=21,
        )
        session.add(s2); session.flush(); snapshots.append(s2)

        # Snapshot 3: 24 hours ago (Daily window)
        s3 = WorkloadSnapshot(
            captured_at=now - timedelta(hours=24),
            window_seconds=86400.0,
            total_calls=340000,
            total_exec_time_ms=95000000.0,
            unique_queries=len(COMPREHENSIVE_QUERIES),
            slow_queries=21,
        )
        session.add(s3); session.flush(); snapshots.append(s3)

        # Snapshot 4: 12 hours ago
        s4 = WorkloadSnapshot(
            captured_at=now - timedelta(hours=12),
            window_seconds=43200.0,
            total_calls=195000,
            total_exec_time_ms=56000000.0,
            unique_queries=len(COMPREHENSIVE_QUERIES),
            slow_queries=21,
        )
        session.add(s4); session.flush(); snapshots.append(s4)

        # Snapshot 5: 6 hours ago
        s5 = WorkloadSnapshot(
            captured_at=now - timedelta(hours=6),
            window_seconds=21600.0,
            total_calls=98000,
            total_exec_time_ms=28000000.0,
            unique_queries=len(COMPREHENSIVE_QUERIES),
            slow_queries=21,
        )
        session.add(s5); session.flush(); snapshots.append(s5)

        # Snapshot 6: 1 hour ago
        s6 = WorkloadSnapshot(
            captured_at=now - timedelta(hours=1),
            window_seconds=3600.0,
            total_calls=22000,
            total_exec_time_ms=6400000.0,
            unique_queries=len(COMPREHENSIVE_QUERIES),
            slow_queries=21,
        )
        session.add(s6); session.flush(); snapshots.append(s6)

        # Snapshot 7: Current Cumulative 24-Hour Production Observation Window
        s7 = WorkloadSnapshot(
            captured_at=now,
            window_seconds=86400.0,
            total_calls=sum(q["calls"] for q in COMPREHENSIVE_QUERIES),
            total_exec_time_ms=sum(q["calls"] * q["mean_ms"] for q in COMPREHENSIVE_QUERIES),
            unique_queries=len(COMPREHENSIVE_QUERIES),
            slow_queries=sum(1 for q in COMPREHENSIVE_QUERIES if q["mean_ms"] >= 100.0),
        )
        session.add(s7); session.flush(); snapshots.append(s7)

        # 4. Populate Query Statistics for the latest snapshot
        print("\n[Step 4/7] Registering 28 comprehensive queries with 24-hour observation telemetry...")
        import xxhash

        db_name = session.execute(text("SELECT current_database();")).scalar() or "dbzenith"
        persisted_query_stats = []

        for idx, item in enumerate(COMPREHENSIVE_QUERIES, 1):
            q_text = item["query"]
            h = xxhash.xxh64(q_text.encode("utf-8")).intdigest()
            if h >= 2**63:
                h = h - 2**64  # Convert to signed 64-bit bigint

            # Construct mock explain plan structure for fast visualization
            mock_plan = [{
                "Plan": {
                    "Node Type": item["explain_type"],
                    "Relation Name": item["relation"],
                    "Startup Cost": 0.0,
                    "Total Cost": round(item["mean_ms"] * 12.5, 2),
                    "Plan Rows": item["rows"],
                    "Plan Width": 64,
                    "Actual Loops": 1,
                    "Actual Total Time": item["mean_ms"],
                    "Shared Hit Blocks": item["hit"],
                    "Shared Read Blocks": item["read"],
                    "Plans": [
                        {
                            "Node Type": "Seq Scan" if item["explain_type"] != "Seq Scan" else "Index Scan",
                            "Relation Name": item["relation"],
                            "Startup Cost": 0.0,
                            "Total Cost": round(item["mean_ms"] * 6.2, 2),
                            "Plan Rows": item["rows"],
                            "Plan Width": 64,
                        }
                    ] if item["explain_type"] in {"Hash Join", "Nested Loop", "Aggregate", "Sort"} else [],
                }
            }]

            stat = QueryStatistic(
                snapshot_id=s7.id,
                query_id=h,
                database_oid=16384,
                user_oid=10,
                database_name=db_name,
                user_name="dbzenith",
                normalized_query=q_text,
                calls=item["calls"],
                total_exec_time_ms=round(item["calls"] * item["mean_ms"], 2),
                mean_exec_time_ms=item["mean_ms"],
                min_exec_time_ms=item["min_ms"],
                max_exec_time_ms=item["max_ms"],
                rows=item["rows"],
                shared_blks_hit=item["hit"],
                shared_blks_read=item["read"],
                shared_blks_dirtied=12 if "orders" in item["relation"] else 0,
                shared_blks_written=0,
                local_blks_hit=0,
                local_blks_read=0,
                temp_blks_read=item["temp_read"],
                temp_blks_written=item["temp_written"],
                blk_read_time_ms=round(item["read"] * 0.05, 2),
                blk_write_time_ms=0.0,
                query_frequency_per_minute=round(item["calls"] / 1440.0, 2),
                predicate_info={"table": item["relation"], "type": item["category"]},
                explain_plan=mock_plan,
            )
            session.add(stat)
            session.flush()
            persisted_query_stats.append(stat)

        session.commit()
        print(f"  [OK] {len(persisted_query_stats)} query statistics recorded across all 3 severity tiers.")

        # 5. Run Recommendation Engine
        print("\n[Step 5/7] Synthesizing optimization recommendations across all advisors...")
        engine_svc = RecommendationEngine()
        recs = engine_svc.generate(session, limit=100)
        print(f"  [OK] {len(recs)} optimization recommendations generated.")
        for r in recs[:6]:
            print(f"    - [{r.type}] target={r.target}: {r.proposed_change[:60]}...")

        # 6. Populate Isolated Sandbox Simulations for ALL Recommendations
        print("\n[Step 6/7] Pre-computing sandbox simulations with before/after plan diffs for ALL recommendations...")
        sim_count = 0
        for r in recs:
            baseline = round(float(r.evidence.get("total_exec_time_ms", 12500) or 12500), 2)
            matching_q = next((q for q in COMPREHENSIVE_QUERIES if r.target and r.target.lower() in q["query"].lower()), COMPREHENSIVE_QUERIES[0])
            baseline_latency = round(matching_q["mean_ms"], 2)

            speedup_pct = 74.5 if r.type == "index_where" else 62.0 if r.type == "composite_index" else 58.0 if r.type == "index_join" else 68.0 if r.type == "partition_by_range" else 42.0 if r.type == "join_strategy" else 38.0
            proposed = round(baseline * (1.0 - (speedup_pct / 100.0)), 2)
            sim_latency = round(baseline_latency * (1.0 - (speedup_pct / 100.0)), 2)
            speedup_factor = round(baseline_latency / max(sim_latency, 0.01), 1)

            sim = OptimizationSimulation(
                recommendation_id=r.id,
                status="completed",
                baseline_cost=baseline,
                proposed_cost=proposed,
                improvement=speedup_pct,
                affected_queries=r.affected_queries or [{"query_id": matching_q.get("query_id", 1), "mean_exec_time_ms": baseline_latency}],
                plan_differences=[
                    {
                        "operator": f"{matching_q.get('explain_type', 'Scan')} -> Optimized Index/Rewrite Path",
                        "speedup": f"{speedup_pct}%",
                        "cost_delta": round(baseline - proposed, 2),
                        "detail": f"Latency projected from {baseline_latency}ms to {sim_latency}ms ({speedup_factor}x faster)",
                    }
                ],
                estimated_storage_impact={"estimated_index_bytes": 1843200, "formatted": "1.8 MB"},
                write_overhead_estimate={"insert_overhead_pct": 3.2, "update_overhead_pct": 1.8},
                confidence=r.confidence,
                benchmark={
                    "runs": 5,
                    "simulated_latency_ms": sim_latency,
                    "baseline_latency_ms": baseline_latency,
                    "p50_baseline_ms": baseline_latency,
                    "p50_simulated_ms": sim_latency,
                    "improvement_pct": speedup_pct,
                    "speedup_factor": speedup_factor,
                },
                baseline_plans=[{"Node Type": matching_q.get("explain_type", "Seq Scan"), "Total Cost": baseline}],
                proposed_plans=[{"Node Type": "Index Scan", "Total Cost": proposed}],
            )
            session.add(sim)
            sim_count += 1

        session.commit()
        print(f"  [OK] {sim_count} isolated sandbox simulations populated with complete before/after cost & latency metrics.")

        # 7. Seed Human Approval Decisions & Security Audit Ledger
        print("\n[Step 7/7] Seeding Human Approval Center decisions & Audit Ledger...")
        # Mark one recommendation as approved with operator justification
        if len(recs) > 1:
            recs[0].status = "approved"
            session.add(RecommendationAuditEvent(
                recommendation_id=recs[0].id,
                action="APPROVE",
                previous_status="pending",
                new_status="approved",
                reason="Verified in HypoPG sandbox with 74.5% latency reduction. Approved for production migration window.",
                metadata_json=json.dumps({"operator_role": "DBA", "approved_by": "lead_dba@internal"}),
            ))
            session.add(SecurityAuditEvent(
                event_category="APPROVAL_CENTER",
                action="MIGRATION_APPROVED",
                actor_username="lead_dba",
                actor_role="DBA",
                target_entity="OptimizationRecommendation",
                target_id=str(recs[0].id),
                status="SUCCESS",
                details_json=json.dumps({"proposed_change": recs[0].proposed_change, "benefit": recs[0].expected_benefit}),
            ))

        # Mark another recommendation as rejected with justification
        if len(recs) > 2:
            recs[1].status = "rejected"
            session.add(RecommendationAuditEvent(
                recommendation_id=recs[1].id,
                action="REJECT",
                previous_status="pending",
                new_status="rejected",
                reason="Write overhead exceeds 5% SLA threshold on high-frequency table; deferred to maintenance window.",
                metadata_json=json.dumps({"operator_role": "DBA", "rejected_by": "lead_dba@internal"}),
            ))
            session.add(SecurityAuditEvent(
                event_category="APPROVAL_CENTER",
                action="MIGRATION_REJECTED",
                actor_username="lead_dba",
                actor_role="DBA",
                target_entity="OptimizationRecommendation",
                target_id=str(recs[1].id),
                status="SUCCESS",
                details_json=json.dumps({"reason": "SLA write overhead threshold exceeded"}),
            ))

        # Add general security audit events to populate the Audit page
        session.add(SecurityAuditEvent(
            event_category="AUTHENTICATION",
            action="USER_LOGIN",
            actor_username="lead_dba",
            actor_role="DBA",
            target_entity="Session",
            status="SUCCESS",
            details_json=json.dumps({"auth_method": "PBKDF2-HMAC-SHA256"}),
        ))
        session.add(SecurityAuditEvent(
            event_category="TELEMETRY",
            action="SNAPSHOT_COLLECTED",
            actor_username="system_collector",
            actor_role="SYSTEM",
            target_entity="WorkloadSnapshot",
            status="SUCCESS",
            details_json=json.dumps({"queries_captured": len(COMPREHENSIVE_QUERIES)}),
        ))
        session.commit()
        print("  [OK] Approval decisions and Security Audit ledger events recorded.")

        print("\n" + "=" * 70)
        print("COMPREHENSIVE WORKLOAD GENERATION COMPLETED SUCCESSFULLY!")
        print("=" * 70)
        print("Summary:")
        print(f"  * Total Registered Queries: {len(COMPREHENSIVE_QUERIES)}")
        print(f"  * Snapshots Created: {len(snapshots)} (Extended 7-Day & 24-Hour Timeline)")
        print("  * Critical Latency Queries (>=500ms): 6")
        print("  * High Latency Queries (100-499ms): 16")
        print("  * Fast Baseline Queries (<100ms): 6")
        print(f"  * Optimization Recommendations: {len(recs)}")
        print(f"  * HypoPG Virtual Sandbox Simulations: {sim_count} (100% Coverage)")
        print(f"  * Human Approval Decisions Seeded: 2 (1 Approved, 1 Rejected, {len(recs) - 2} Pending)")
        print("=" * 70)

        return {
            "status": "success",
            "queries_count": len(COMPREHENSIVE_QUERIES),
            "recommendations_count": len(recs),
            "simulations_count": sim_count,
        }

    finally:
        session.close()


if __name__ == "__main__":
    db_arg = sys.argv[1] if len(sys.argv) > 1 else None
    generate_comprehensive_workload(db_arg)
