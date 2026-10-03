from __future__ import annotations

from app.services.privacy.audit import audit_privacy_event
from app.services.privacy.contracts import AIWorkloadRecord, RawPlan, RawQuery, SanitizedPlan, SanitizedQuery
from app.services.privacy.policy import PrivacyPolicyEngine
from app.services.privacy.sanitizer import sanitize_plan, sanitize_query


class PrivacyGateway:
    """Mandatory boundary from raw telemetry to AI-safe workload contracts."""

    def __init__(self, policy: PrivacyPolicyEngine | None = None) -> None:
        self.policy = policy or PrivacyPolicyEngine()

    def sanitize_query(self, raw: RawQuery) -> SanitizedQuery:
        try:
            sanitized = sanitize_query(raw)
            decision = self.policy.evaluate_query(sanitized)
        except Exception as exc:
            audit_privacy_event("query_sanitization_failed", allowed=False, reason=type(exc).__name__)
            raise ValueError("query could not be safely sanitized") from exc
        audit_privacy_event(
            "query_sanitized",
            allowed=decision.allowed,
            reason=decision.reason,
            query_id=raw.query_id,
            structural_hash=sanitized.structural_hash,
        )
        if not decision.allowed:
            raise ValueError("sanitized query failed privacy policy")
        return sanitized

    def sanitize_plan(self, raw: RawPlan) -> SanitizedPlan:
        try:
            sanitized = sanitize_plan(raw)
            decision = self.policy.evaluate_plan(sanitized)
        except Exception as exc:
            audit_privacy_event("plan_sanitization_failed", allowed=False, reason=type(exc).__name__)
            raise ValueError("plan could not be safely sanitized") from exc
        audit_privacy_event(
            "plan_sanitized",
            allowed=decision.allowed,
            reason=decision.reason,
            query_id=raw.query_id,
            structural_hash=sanitized.structural_hash,
        )
        if not decision.allowed:
            raise ValueError("sanitized plan failed privacy policy")
        return sanitized

    def build_ai_record(
        self,
        raw_query: RawQuery,
        *,
        calls: int,
        query_frequency_per_minute: float,
        duration_ms_bucket: int,
        rows_bucket: int,
        sample_count: int,
        raw_plan: RawPlan | None = None,
    ) -> AIWorkloadRecord:
        query = self.sanitize_query(raw_query)
        plan = self.sanitize_plan(raw_plan) if raw_plan is not None else None
        record = AIWorkloadRecord(
            query=query,
            plan=plan,
            calls=calls,
            query_frequency_per_minute=query_frequency_per_minute,
            duration_ms_bucket=duration_ms_bucket,
            rows_bucket=rows_bucket,
            sample_count=sample_count,
        )
        decision = self.policy.evaluate_ai_record(record)
        audit_privacy_event("ai_record_boundary_check", allowed=decision.allowed, reason=decision.reason)
        if not decision.allowed:
            raise ValueError("AI record failed privacy policy")
        return record
