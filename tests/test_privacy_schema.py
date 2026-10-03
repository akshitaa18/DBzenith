import pytest
from pydantic import ValidationError

from app.schemas.privacy import SanitizedWorkload


def test_sanitized_workload_forbids_unexpected_fields() -> None:
    payload = {
        "normalized_sql": "SELECT * FROM users WHERE id = ?",
        "query_hash": "12345678abcdef",
        "operator_types": ["Seq Scan"],
        "join_edges": [],
        "duration_ms_bucket": 100,
        "rows_bucket": 100,
        "sample_count": 10,
        "raw_row": {"email": "person@example.com"},
    }
    with pytest.raises(ValidationError):
        SanitizedWorkload.model_validate(payload)


def test_sanitized_workload_accepts_safe_representation() -> None:
    item = SanitizedWorkload(
        normalized_sql="SELECT * FROM users WHERE id = ?",
        query_hash="12345678abcdef",
        operator_types=["Index Scan"],
        join_edges=[] ,
        duration_ms_bucket=50,
        rows_bucket=10,
        sample_count=3,
    )
    assert item.query_hash == "12345678abcdef"
