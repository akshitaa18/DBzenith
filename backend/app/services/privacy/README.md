# Privacy Gateway

This package is the mandatory security boundary between raw PostgreSQL telemetry and future AI consumers.

## Flow

`RawQuery` / `RawPlan` -> parser/sanitizer -> `SanitizedQuery` / `SanitizedPlan` -> policy engine -> `AIWorkloadRecord` -> AI boundary.

The gateway fails closed on parsing, sanitization, or policy errors and emits security audit events without logging raw payloads.
