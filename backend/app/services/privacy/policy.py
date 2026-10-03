from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any

from app.services.privacy.contracts import AIWorkloadRecord, SanitizedPlan, SanitizedQuery

_SECRET_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"),
    re.compile(r"\b(?:sk|pk|api[_-]?key|token|secret)[_-]?[A-Za-z0-9_-]{12,}\b", re.I),
    re.compile(r"\bpassword\s*[:=]\s*\S+", re.I),
]


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PrivacyPolicyEngine:
    """Fail-closed validation for the AI boundary."""

    def evaluate_query(self, query: SanitizedQuery) -> PolicyDecision:
        if self._contains_secret(query.normalized_sql):
            return PolicyDecision(False, "sanitized_query_contains_sensitive_pattern")
        if any(v < 0 for v in query.literal_counts.values()):
            return PolicyDecision(False, "invalid_literal_count")
        return PolicyDecision(True, "allowed")

    def evaluate_plan(self, plan: SanitizedPlan) -> PolicyDecision:
        if self._contains_secret(repr(plan.plan)):
            return PolicyDecision(False, "sanitized_plan_contains_sensitive_pattern")
        return PolicyDecision(True, "allowed")

    def evaluate_ai_record(self, record: AIWorkloadRecord) -> PolicyDecision:
        q = self.evaluate_query(record.query)
        if not q.allowed:
            return q
        if record.plan is not None:
            return self.evaluate_plan(record.plan)
        return PolicyDecision(True, "allowed")

    @staticmethod
    def _contains_secret(value: str) -> bool:
        for pattern in _SECRET_PATTERNS:
            if pattern.search(value):
                return True
        # IPv4 values should never survive sanitization.
        for token in value.split():
            try:
                ipaddress.ip_address(token.strip("(),;"))
                return True
            except ValueError:
                continue
        return False
