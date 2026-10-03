import inspect
from typing import get_type_hints

import pytest

from app.services.ai.boundary import AIBoundaryValidator
from app.services.privacy.contracts import AIWorkloadRecord, RawPlan, RawQuery


def test_ai_validator_accepts_only_sanitized_contract() -> None:
    signature = inspect.signature(AIBoundaryValidator.validate)
    hints = get_type_hints(AIBoundaryValidator.validate)
    assert hints["record"] is AIWorkloadRecord
    assert signature.parameters["record"].name == "record"


def test_raw_query_and_raw_plan_are_rejected() -> None:
    validator = AIBoundaryValidator()
    with pytest.raises(TypeError):
        validator.validate(RawQuery(sql="SELECT 1"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        validator.validate(RawPlan(plan={"Plan": {}}))  # type: ignore[arg-type]
