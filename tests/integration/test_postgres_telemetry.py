import os

import pytest
from sqlalchemy import create_engine, text

from app.services.collector.telemetry import TelemetryCollector


DATABASE_URL = os.getenv("DBZENITH_INTEGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")


def _postgres_available() -> bool:
    if not DATABASE_URL or not DATABASE_URL.startswith("postgresql"):
        return False
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.integration


@pytest.mark.skipif(not _postgres_available(), reason="PostgreSQL integration database is unavailable")
def test_pg_stat_statements_is_enabled():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        enabled = conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements')")
        ).scalar()
        preload = conn.execute(
            text("SELECT current_setting('shared_preload_libraries') LIKE '%pg_stat_statements%'")
        ).scalar()
    assert enabled is True
    assert preload is True


@pytest.mark.skipif(not _postgres_available(), reason="PostgreSQL integration database is unavailable")
def test_real_telemetry_snapshot_contains_pg_statistics():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS telemetry_test (id integer, value text)"))
        conn.execute(text("INSERT INTO telemetry_test VALUES (1, 'a'), (2, 'b')"))
        conn.execute(text("SELECT count(*) FROM telemetry_test"))

    collector = TelemetryCollector()
    snapshot = collector.collect_once()
    assert snapshot.unique_queries >= 1
    assert snapshot.total_calls >= 1
