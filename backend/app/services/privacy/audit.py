from __future__ import annotations

import json
import logging
from typing import Any

from app.db.session import get_session_factory
from app.models.privacy import PrivacyAuditEvent

logger = logging.getLogger("dbzenith.security.audit")


def audit_privacy_event(event: str, *, allowed: bool, reason: str, **metadata: Any) -> None:
    """Record a privacy-boundary decision without ever persisting raw payloads."""
    safe = {k: v for k, v in metadata.items() if k not in {"sql", "raw_sql", "plan", "raw_plan", "payload"}}
    logger.info(
        "privacy_boundary_event",
        extra={"event": event, "allowed": allowed, "reason": reason, **safe},
    )
    try:
        import psycopg  # type: ignore[import-not-found]
        _ = psycopg
        with get_session_factory()() as db:
            db.add(
                PrivacyAuditEvent(
                    event=event,
                    allowed=allowed,
                    reason=reason,
                    query_id=safe.get("query_id"),
                    structural_hash=safe.get("structural_hash"),
                    metadata_json=json.dumps(safe, default=str),
                )
            )
            db.commit()
    except ModuleNotFoundError:
        logger.debug("privacy_audit_storage_driver_unavailable")
    except Exception:
        # The security decision must not be weakened by an audit-storage outage.
        logger.warning("privacy_audit_persistence_failed", extra={"event": "privacy_audit_persistence_failed"})
