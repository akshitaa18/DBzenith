"""Main entrypoint for safe SQL AST rewriting in DBZenith."""

from __future__ import annotations

from typing import Any
import sqlglot
from sqlglot import exp

from app.services.rewriter.ast_transformer import SQLASTTransformer
from app.services.rewriter.contracts import (
    SQLRewriteResult,
    TransformationType,
    ValidationStatus,
)
from app.services.rewriter.safety import SQLRewriteSafetyPolicy
from app.services.rewriter.sandbox_validator import SandboxRewriteValidator


class SQLRewriteEngine:
    """Safe, AST-based SQL rewriting engine with sandbox validation and semantic protection."""

    def __init__(
        self,
        validator: SandboxRewriteValidator | None = None,
        safety_policy: SQLRewriteSafetyPolicy | None = None,
    ) -> None:
        self.validator = validator or SandboxRewriteValidator()
        self.safety_policy = safety_policy or SQLRewriteSafetyPolicy()

    def rewrite(
        self,
        sql: str,
        validate_sandbox: bool = True,
        engine_override: Any | None = None,
        query_id: str | None = None,
    ) -> SQLRewriteResult:
        """Transforms a candidate SQL query, validating semantics in the sandbox."""
        original_sql = sql.strip().rstrip(";")

        # 1. Pre-validation safety checks
        is_safe, reason = self.safety_policy.check_query_safety(original_sql)
        if not is_safe:
            return SQLRewriteResult(
                original_query=original_sql,
                rewritten_query=original_sql,
                transformation=TransformationType.NO_OP.value,
                reason=reason or "Safety policy violation.",
                expected_benefit="None - rejected unsafe query.",
                confidence=0.0,
                validation_status=ValidationStatus.UNSAFE_REJECTED.value,
                safety_verdict="unsafe",
                rejection_reason=reason,
                production_modified=False,
            )

        # 2. Parse AST
        ast = sqlglot.parse_one(original_sql, read="postgres")

        # 3. Attempt conservative AST transformations in priority order
        transformations = [
            (
                TransformationType.REDUNDANT_DISTINCT_ELIMINATION,
                SQLASTTransformer.transform_redundant_distinct,
                "Query includes DISTINCT alongside matching GROUP BY aggregation.",
                "Eliminates redundant sorting or hashing pass after aggregation.",
                0.95,
            ),
            (
                TransformationType.OR_TO_IN_LIST,
                SQLASTTransformer.transform_or_to_in,
                "Chained equality comparisons on the same column can be represented as an IN-list.",
                "Allows PostgreSQL optimizer to use array index scans or bitmap scans instead of multiple branches.",
                0.90,
            ),
            (
                TransformationType.EXISTS_SELECT_ONE_SIMPLIFICATION,
                SQLASTTransformer.transform_exists_select_one,
                "EXISTS subqueries only require boolean presence checks, not full column projection.",
                "Eliminates unnecessary targetlist resolution and column overhead inside subqueries.",
                0.92,
            ),
            (
                TransformationType.IN_SUBQUERY_ORDER_BY_ELIMINATION,
                SQLASTTransformer.transform_in_subquery_order_by,
                "IN predicate subqueries evaluate unordered set membership; ORDER BY is redundant without LIMIT.",
                "Eliminates expensive sort operations inside subqueries.",
                0.94,
            ),
            (
                TransformationType.LEFT_JOIN_TO_INNER_JOIN,
                SQLASTTransformer.transform_left_to_inner_join,
                "Outer WHERE predicate strictly filters out NULL values on the right-hand joined table.",
                "Allows query planner to reorder joins and employ hash/merge join algorithms.",
                0.88,
            ),
        ]

        applied_type = None
        new_ast = ast
        trans_reason = None
        trans_benefit = None
        confidence = 0.0
        ast_diff = None

        for t_type, t_func, t_reason, t_benefit, t_conf in transformations:
            candidate_ast, changed, diff_note = t_func(new_ast)
            if changed:
                applied_type = t_type
                new_ast = candidate_ast
                trans_reason = t_reason
                trans_benefit = t_benefit
                confidence = t_conf
                ast_diff = diff_note
                break

        # 4. If no transformation matched
        if applied_type is None:
            return SQLRewriteResult(
                original_query=original_sql,
                rewritten_query=original_sql,
                transformation=TransformationType.NO_OP.value,
                reason="Query is already in canonical or optimal shape.",
                expected_benefit="No AST transformation was required.",
                confidence=1.0,
                validation_status=ValidationStatus.VALIDATED_IN_SANDBOX.value,
                safety_verdict="safe",
                production_modified=False,
            )

        # 5. Post-transformation safety verification
        is_safe, post_reason = self.safety_policy.check_transformation_safety(ast, new_ast)
        if not is_safe:
            return SQLRewriteResult(
                original_query=original_sql,
                rewritten_query=original_sql,
                transformation=applied_type.value,
                reason=f"Transformation aborted due to safety constraint: {post_reason}",
                expected_benefit="None",
                confidence=0.0,
                validation_status=ValidationStatus.UNSAFE_REJECTED.value,
                safety_verdict="unsafe",
                rejection_reason=post_reason,
                production_modified=False,
            )

        rewritten_sql = new_ast.sql(dialect="postgres")

        # 6. Sandbox validation
        if validate_sandbox:
            val_result = self.validator.validate_rewrite(
                original_sql,
                rewritten_sql,
                engine_override=engine_override,
            )
            return SQLRewriteResult(
                original_query=original_sql,
                rewritten_query=rewritten_sql,
                transformation=applied_type.value,
                reason=trans_reason or "AST optimization applied.",
                expected_benefit=trans_benefit or "Improved optimizer efficiency.",
                confidence=confidence,
                validation_status=val_result["validation_status"],
                safety_verdict="safe" if val_result["validation_status"] == ValidationStatus.VALIDATED_IN_SANDBOX.value else "rejected",
                rejection_reason=val_result.get("rejection_reason"),
                ast_diff=ast_diff,
                baseline_cost=val_result.get("baseline_cost"),
                rewritten_cost=val_result.get("rewritten_cost"),
                cost_improvement_pct=val_result.get("cost_improvement_pct"),
                semantic_match=val_result.get("semantic_match"),
                production_modified=False,
            )

        return SQLRewriteResult(
            original_query=original_sql,
            rewritten_query=rewritten_sql,
            transformation=applied_type.value,
            reason=trans_reason or "AST optimization applied.",
            expected_benefit=trans_benefit or "Improved optimizer efficiency.",
            confidence=confidence,
            validation_status=ValidationStatus.PENDING.value,
            safety_verdict="safe",
            ast_diff=ast_diff,
            production_modified=False,
        )


_rewrite_engine_instance: SQLRewriteEngine | None = None


def get_rewrite_engine() -> SQLRewriteEngine:
    """Returns singleton instance of the SQLRewriteEngine."""
    global _rewrite_engine_instance
    if _rewrite_engine_instance is None:
        _rewrite_engine_instance = SQLRewriteEngine()
    return _rewrite_engine_instance

