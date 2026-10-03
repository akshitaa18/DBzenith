from sqlalchemy import BigInteger, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RelationStatistic(Base):
    __tablename__ = "relation_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("workload_snapshots.id", ondelete="CASCADE"), index=True)
    schema_name: Mapped[str] = mapped_column(Text, nullable=False)
    relation_name: Mapped[str] = mapped_column(Text, nullable=False)
    seq_scan: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    idx_scan: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    n_live_tup: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    n_dead_tup: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    table_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    index_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
