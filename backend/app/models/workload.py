from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WorkloadSnapshot(Base):
    __tablename__ = "workload_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    window_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_calls: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_exec_time_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unique_queries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    slow_queries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    query_stats: Mapped[list["QueryStatistic"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class QueryStatistic(Base):
    __tablename__ = "query_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("workload_snapshots.id", ondelete="CASCADE"), index=True)
    query_id: Mapped[int] = mapped_column(BigInteger, index=True)
    database_oid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    user_oid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    database_name: Mapped[str | None] = mapped_column(Text)
    user_name: Mapped[str | None] = mapped_column(Text)
    normalized_query: Mapped[str] = mapped_column(Text, nullable=False)
    calls: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_exec_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    mean_exec_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    min_exec_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    max_exec_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    rows: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shared_blks_hit: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shared_blks_read: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shared_blks_dirtied: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shared_blks_written: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    local_blks_hit: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    local_blks_read: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    temp_blks_read: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    temp_blks_written: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    blk_read_time_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    blk_write_time_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    query_frequency_per_minute: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    predicate_info: Mapped[dict | None] = mapped_column(JSONB)
    explain_plan: Mapped[list | dict | None] = mapped_column(JSONB)

    snapshot: Mapped[WorkloadSnapshot] = relationship(back_populates="query_stats")
