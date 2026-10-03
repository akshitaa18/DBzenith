"""Audit logging and conversation history persistence for the DBA Assistant."""

from __future__ import annotations

import datetime
from typing import Any
from app.services.assistant.contracts import AuditEvent


class AssistantAuditLogger:
    """Maintains an audit ledger of all assistant queries, security checks, and tool executions."""

    def __init__(self) -> None:
        self._audit_records: list[dict[str, Any]] = []
        self._conversations: dict[str, list[dict[str, str]]] = {}

    def log_event(
        self,
        session_id: str,
        event_type: str,
        tool_name: str | None = None,
        input_payload: dict[str, Any] | None = None,
        output_summary: str | None = None,
        authorized: bool = True,
        security_flag: str | None = None,
    ) -> dict[str, Any]:
        """Appends an immutable audit event."""
        event = AuditEvent(
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            session_id=session_id,
            event_type=event_type,
            tool_name=tool_name,
            input_payload=input_payload or {},
            output_summary=output_summary,
            authorized=authorized,
            security_flag=security_flag,
        )
        data = event.model_dump()
        self._audit_records.append(data)
        return data

    def record_turn(self, session_id: str, user_msg: str, assistant_reply: str) -> None:
        """Stores a conversation turn under the session."""
        if session_id not in self._conversations:
            self._conversations[session_id] = []
        self._conversations[session_id].append({"role": "user", "content": user_msg})
        self._conversations[session_id].append({"role": "assistant", "content": assistant_reply})

    def get_session_history(self, session_id: str) -> list[dict[str, str]]:
        return self._conversations.get(session_id, [])

    def get_session_audit_trail(self, session_id: str) -> list[dict[str, Any]]:
        return [r for r in self._audit_records if r["session_id"] == session_id]

    def all_audit_records(self) -> list[dict[str, Any]]:
        return list(self._audit_records)


_audit_logger_instance: AssistantAuditLogger | None = None


def get_assistant_audit_logger() -> AssistantAuditLogger:
    global _audit_logger_instance
    if _audit_logger_instance is None:
        _audit_logger_instance = AssistantAuditLogger()
    return _audit_logger_instance
