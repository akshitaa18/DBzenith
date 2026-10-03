from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Recommendation:
    key: str
    type: str
    target: str
    proposed_change: str
    reason: str
    evidence: dict[str, Any]
    expected_benefit: str
    risk: str
    confidence: float
    affected_queries: list[dict[str, Any]] = field(default_factory=list)
    requires_approval: bool = True
