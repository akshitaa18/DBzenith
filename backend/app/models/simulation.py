from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OptimizationSimulation(Base):
    __tablename__ = "optimization_simulations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    recommendation_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="completed", index=True)
    baseline_cost: Mapped[float | None] = mapped_column(Float)
    proposed_cost: Mapped[float | None] = mapped_column(Float)
    improvement: Mapped[float | None] = mapped_column(Float)
    affected_queries: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    plan_differences: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    estimated_storage_impact: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    write_overhead_estimate: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    limitations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    benchmark: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    baseline_plans: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    proposed_plans: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text)
