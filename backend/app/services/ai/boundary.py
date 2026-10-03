"""AI boundary enforcement.

AI-facing code imports this module and accepts AIWorkloadRecord only. RawQuery and
RawPlan are deliberately not accepted, even if a caller tries to pass a subclass
or a dict that resembles a raw contract.
"""

from __future__ import annotations

from app.services.privacy.contracts import AIWorkloadRecord
from app.services.privacy.policy import PrivacyPolicyEngine


class AIBoundaryValidator:
    def __init__(self, policy: PrivacyPolicyEngine | None = None) -> None:
        self.policy = policy or PrivacyPolicyEngine()

    def validate(self, record: AIWorkloadRecord) -> AIWorkloadRecord:
        if not isinstance(record, AIWorkloadRecord):
            raise TypeError("AI modules accept AIWorkloadRecord only")
        decision = self.policy.evaluate_ai_record(record)
        if not decision.allowed:
            raise ValueError(f"AI boundary rejected record: {decision.reason}")
        return record
