from datetime import datetime

from pydantic import BaseModel, ConfigDict


class QueryDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    query_id: int
    database_name: str | None
    user_name: str | None
    normalized_query: str
    calls: int
    total_exec_time_ms: float
    mean_exec_time_ms: float
    min_exec_time_ms: float
    max_exec_time_ms: float
    rows: int
    shared_blks_hit: int
    shared_blks_read: int
    shared_blks_dirtied: int
    shared_blks_written: int
    local_blks_hit: int
    local_blks_read: int
    temp_blks_read: int
    temp_blks_written: int
    blk_read_time_ms: float
    blk_write_time_ms: float
    query_frequency_per_minute: float
    predicate_info: dict | None
    explain_plan: list | dict | None

    @classmethod
    def from_model(cls, value):
        return cls.model_validate(value)


class PaginatedQueries(BaseModel):
    items: list[QueryDetail]
    page: int
    page_size: int
    total: int


class WorkloadSummary(BaseModel):
    snapshot_id: int | None
    captured_at: datetime | None
    window_seconds: float
    total_calls: int
    total_exec_time_ms: float
    unique_queries: int
    slow_queries: int
    top_queries: list[dict]
