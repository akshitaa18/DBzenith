"""Prompt injection defense, safety invariants, and tool authorization for the DBA Assistant."""

from __future__ import annotations

import re
from typing import Any
from app.services.assistant.contracts import ControlledToolName, UserRole


class SecurityViolationError(PermissionError):
    """Raised when an operation violates conversational DBA assistant safety invariants."""
    pass


class PromptInjectionError(SecurityViolationError):
    """Raised when user prompt contains prompt injection or instruction override patterns."""
    pass


# Prompt injection & jailbreak patterns
_PROMPT_INJECTION_PATTERNS = [
    r"(?i)\bignore\s+(all\s+)?(previous|prior)\s+instructions\b",
    r"(?i)\byou\s+are\s+now\s+(in\s+)?(dan|jailbreak|developer|god|maintenance)\s+mode\b",
    r"(?i)\bdisregard\s+(all\s+)?(safety|rules|constraints|policies)\b",
    r"(?i)\bnew\s+system\s+prompt\b",
    r"(?i)\bbypass\s+(all\s+)?(guards?|filters?|privacy|security|gateway)\b",
    r"(?i)\bpretend\s+you\s+(are\s+not|have\s+no)\s+(an\s+ai|rules|restrictions)\b",
    r"(?i)\bprint\s+(your\s+)?(system\s+prompt|initial\s+instructions)\b",
    r"(?i)\brepeat\s+(all\s+words\s+above|the\s+text\s+above)\b",
    r"(?i)\boverride\s+(system|guardrails|safety)\b",
    r"(?i)\bact\s+as\s+(an\s+unrestricted|root|sudo)\b",
]

# Raw SQL execution patterns
_RAW_SQL_EXECUTION_PATTERNS = [
    r"(?i)\bexecute\s+(raw\s+)?sql\b",
    r"(?i)\brun\s+arbitrary\s+query\b",
    r"(?i)\b(insert\s+into|update\s+\w+\s+set|delete\s+from|drop\s+table|truncate\s+table|alter\s+table)\b",
    r"(?i)\bgrant\s+\w+\s+to\b",
    r"(?i)\bunion\s+select\b",
]

# Raw production data access patterns
_RAW_DATA_ACCESS_PATTERNS = [
    r"(?i)\b(dump|extract|show|leak)\s+(all\s+)?(passwords|credit_cards?|pii|credentials|secret)\b",
    r"(?i)\bbypass\s+privacy\s+gateway\b",
    r"(?i)\bshow\s+raw\s+production\s+(data|rows|records|tuples)\b",
]

# Direct modification or self-approval patterns
_DIRECT_MUTATION_PATTERNS = [
    r"(?i)\bapply\b.*\bproduction\b",
    r"(?i)\b(modify|mutate|change)\b.*\bproduction\b",
    r"(?i)\b(auto[- ]?approve|approve\s+your\s+own|self[- ]?approve)\b",
    r"(?i)\bapprove\s+(and\s+apply|recommendation|directly)\b",
]



class AssistantSafetyPolicy:
    """Enforces prompt-injection defenses and strict DBA safety invariants."""

    @classmethod
    def evaluate_user_prompt(cls, user_prompt: str) -> tuple[bool, str | None]:
        """Scans user input for prompt injection, arbitrary SQL, raw data leaks, and direct mutations."""
        text = user_prompt.strip()

        # 1. Prompt Injection Checks
        for pat in _PROMPT_INJECTION_PATTERNS:
            if re.search(pat, text):
                return False, "Prompt injection attempt detected: instruction override patterns are strictly forbidden."

        # 2. Arbitrary SQL Execution Checks
        for pat in _RAW_SQL_EXECUTION_PATTERNS:
            if re.search(pat, text):
                return False, "Arbitrary SQL execution is strictly forbidden. The assistant only interacts via controlled telemetry tools."

        # 3. Raw Production Data Access Checks
        for pat in _RAW_DATA_ACCESS_PATTERNS:
            if re.search(pat, text):
                return False, "Direct raw production data access forbidden. All telemetry must pass through the privacy gateway."

        # 4. Direct Production Mutation or Self-Approval Checks
        for pat in _DIRECT_MUTATION_PATTERNS:
            if re.search(pat, text):
                return False, "Direct production modification and self-approval are strictly forbidden. Changes require human DBA review."

        return True, None

    @classmethod
    def assert_safe_prompt(cls, user_prompt: str) -> None:
        """Raises SecurityViolationError if the prompt fails safety evaluation."""
        is_safe, reason = cls.evaluate_user_prompt(user_prompt)
        if not is_safe:
            raise SecurityViolationError(reason)


class ToolAuthorizer:
    """Manages role-based authorization for controlled DBA tools."""

    # Role permissions mapping
    _ROLE_PERMISSIONS: dict[UserRole, set[ControlledToolName]] = {
        UserRole.ADMIN: set(ControlledToolName),  # Full access to controlled tools
        UserRole.DBA: set(ControlledToolName),    # Full access to controlled tools
        UserRole.ANALYST: {
            ControlledToolName.GET_SLOW_QUERIES,
            ControlledToolName.GET_QUERY_DETAILS,
            ControlledToolName.GET_EXECUTION_PLAN,
            ControlledToolName.ANALYZE_PLAN,
            ControlledToolName.GET_RECOMMENDATIONS,
            ControlledToolName.EXPLAIN_BOTTLENECK,
            ControlledToolName.GET_WORKLOAD_SUMMARY,
        },
        UserRole.VIEWER: {
            ControlledToolName.GET_SLOW_QUERIES,
            ControlledToolName.GET_QUERY_DETAILS,
            ControlledToolName.GET_WORKLOAD_SUMMARY,
        },
        UserRole.UNAUTHORIZED: set(),
    }

    @classmethod
    def check_tool_authorization(cls, tool_name: ControlledToolName | str, user_role: UserRole | str) -> tuple[bool, str | None]:
        """Verifies if the given user role is authorized to invoke the specified controlled tool."""
        # Normalize role
        if isinstance(user_role, UserRole):
            role_enum = user_role
        else:
            try:
                role_enum = UserRole(str(user_role).lower())
            except ValueError:
                role_enum = UserRole.UNAUTHORIZED

        # Normalize tool
        if isinstance(tool_name, ControlledToolName):
            tool_enum = tool_name
        else:
            try:
                tool_enum = ControlledToolName(str(tool_name))
            except ValueError:
                return False, f"Tool '{tool_name}' is not an authorized controlled tool."


        allowed_tools = cls._ROLE_PERMISSIONS.get(role_enum, set())
        if tool_enum not in allowed_tools:
            return False, f"Role '{role_enum.value}' is not authorized to execute tool '{tool_enum.value}'."

        return True, None

    @classmethod
    def assert_authorized(cls, tool_name: ControlledToolName | str, user_role: UserRole | str) -> None:
        authorized, reason = cls.check_tool_authorization(tool_name, user_role)
        if not authorized:
            raise SecurityViolationError(reason)
