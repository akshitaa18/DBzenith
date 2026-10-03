import pytest
from pydantic import ValidationError

from app.schemas.privacy import SanitizedWorkload


def test_sanitized_workload_forbids_unexpected_fields() -> None:
    payload = {
        "normalized_sql": "SELECT * FROM id_a WHERE id = <NUM>",
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
