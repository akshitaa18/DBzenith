"""DBZenith Safe SQL Rewriting Subsystem.

Features:
- AST transformations with sqlglot
- Conservative semantic preservation
- Sandbox execution & regression verification
- Production safety invariants
"""

from app.services.rewriter.ast_transformer import SQLASTTransformer
from app.services.rewriter.contracts import (
    SQLRewriteResult,
    TransformationType,
    ValidationStatus,
)
from app.services.rewriter.engine import SQLRewriteEngine, get_rewrite_engine
from app.services.rewriter.safety import SQLRewriteSafetyPolicy
from app.services.rewriter.sandbox_validator import SandboxRewriteValidator

__all__ = [
    "TransformationType",
    "ValidationStatus",
    "SQLRewriteResult",
    "SQLRewriteSafetyPolicy",
    "SQLASTTransformer",
    "SandboxRewriteValidator",
    "SQLRewriteEngine",
    "get_rewrite_engine",
]
