from app.services.privacy.contracts import AIWorkloadRecord, RawPlan, RawQuery, SanitizedPlan, SanitizedQuery

# Backward-compatible export retained for the v0.2 privacy schema tests.
SanitizedWorkload = AIWorkloadRecord

__all__ = ["RawQuery", "SanitizedQuery", "RawPlan", "SanitizedPlan", "AIWorkloadRecord", "SanitizedWorkload"]
