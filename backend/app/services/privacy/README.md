# Privacy Service Boundary

This package is the architectural boundary between production telemetry and future AI consumers.

Only sanitized representations such as `SanitizedWorkload` are permitted to cross into AI-facing code.
A production sanitizer/telemetry pipeline is intentionally deferred to a later phase.
