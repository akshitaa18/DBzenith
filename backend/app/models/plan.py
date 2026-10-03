from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlanAnalysis(Base):
    __tablename__ = "plan_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    query_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    structural_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sanitized_plan: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    graph: Mapped[dict] = mapped_column(JSONB, nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    bottlenecks: Mapped[list] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[dict] = mapped_column(JSONB, nullable=False)
