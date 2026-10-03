from pydantic import BaseModel, ConfigDict, Field


class SanitizedWorkload(BaseModel):
    """AI-boundary-safe workload representation; raw data is intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    normalized_sql: str = Field(min_length=1, max_length=10_000)
    query_hash: str = Field(min_length=8, max_length=128)
    operator_types: list[str] = Field(default_factory=list, max_length=100)
    join_edges: list[tuple[str, str]] = Field(default_factory=list, max_length=100)
    duration_ms_bucket: int = Field(ge=0)
    rows_bucket: int = Field(ge=0)
    sample_count: int = Field(ge=0)
