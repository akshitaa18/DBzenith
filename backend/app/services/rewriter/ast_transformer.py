"""Conservative SQL AST transformations using sqlglot.

Every transformation preserves relational semantics and produces explainable optimizer benefits.
"""

from __future__ import annotations

import copy
from typing import Any
import sqlglot
from sqlglot import exp

from app.services.rewriter.contracts import TransformationType


class SQLASTTransformer:
    """Performs conservative, semantically verifiable SQL AST transformations."""

    @classmethod
    def transform_or_to_in(cls, ast: exp.Expression) -> tuple[exp.Expression, bool, str | None]:
        """Converts chained equality OR conditions on the same column into an IN list.

        Example:
            WHERE col = 1 OR col = 2 OR col = 3
            ->
            WHERE col IN (1, 2, 3)
        Benefit:
            Allows PostgreSQL optimizer to use array-based index scans or bitmap index scans.
        """
        transformed = False
        diff_note = None
        new_ast = ast.copy()

        def _flatten_or(node: exp.Expression) -> list[exp.Expression]:
            if isinstance(node, exp.Or):
                return _flatten_or(node.this) + _flatten_or(node.expression)
            return [node]

        # Scan for WHERE clauses
        for where in new_ast.find_all(exp.Where):
            condition = where.this
            or_nodes = _flatten_or(condition)
            if len(or_nodes) < 2:
                continue

            # Check if all branches are equality comparisons
            first = or_nodes[0]
            if not isinstance(first, exp.EQ):
                continue

            target_col = first.left
            target_col_sql = target_col.sql(dialect="postgres")
            values = []
            valid_pattern = True

            for branch in or_nodes:
                if not isinstance(branch, exp.EQ):
                    valid_pattern = False
                    break
                if branch.left.sql(dialect="postgres") != target_col_sql:
                    valid_pattern = False
                    break
                values.append(branch.right)

            if valid_pattern and len(values) >= 2:
                in_expr = exp.In(this=target_col.copy(), expressions=[v.copy() for v in values])
                where.set("this", in_expr)
                transformed = True
                diff_note = f"Converted {len(values)} OR equality predicates on '{target_col_sql}' into single IN list."
                break

        return new_ast, transformed, diff_note

    @classmethod
    def transform_exists_select_one(cls, ast: exp.Expression) -> tuple[exp.Expression, bool, str | None]:
        """Simplifies EXISTS subqueries by replacing projected columns with SELECT 1.

        Example:
            WHERE EXISTS (SELECT * FROM orders WHERE ...)
            ->
            WHERE EXISTS (SELECT 1 FROM orders WHERE ...)
        Benefit:
            Eliminates unnecessary column projection and targetlist resolution in subqueries.
        """
        transformed = False
        diff_note = None
        new_ast = ast.copy()

        for exists_node in new_ast.find_all(exp.Exists):
            subquery = exists_node.this
            # Target inner select
            inner_select = subquery.this if hasattr(subquery, "this") and isinstance(subquery.this, exp.Select) else subquery
            if isinstance(inner_select, exp.Select):
                curr_exprs = inner_select.expressions
                # If projecting Star or specific non-literal columns
                if curr_exprs and not (len(curr_exprs) == 1 and isinstance(curr_exprs[0], exp.Literal)):
                    inner_select.set("expressions", [exp.Literal.number(1)])
                    transformed = True
                    diff_note = "Replaced subquery column projection with SELECT 1 inside EXISTS predicate."
                    break

        return new_ast, transformed, diff_note

    @classmethod
    def transform_in_subquery_order_by(cls, ast: exp.Expression) -> tuple[exp.Expression, bool, str | None]:
        """Eliminates redundant ORDER BY inside IN subqueries without LIMIT/OFFSET.

        Example:
            WHERE id IN (SELECT customer_id FROM orders ORDER BY order_date DESC)
            ->
            WHERE id IN (SELECT customer_id FROM orders)
        Benefit:
            Eliminates expensive sort node; set membership is mathematically order-invariant.
        """
        transformed = False
        diff_note = None
        new_ast = ast.copy()

        for in_node in new_ast.find_all(exp.In):
            # Target inner query
            sub = in_node.args.get("query") or in_node.this
            inner = sub.this if hasattr(sub, "this") and isinstance(sub.this, exp.Select) else sub
            if isinstance(inner, exp.Select) and inner.args.get("order"):
                # Only safe if there is NO limit / offset
                if not inner.args.get("limit") and not inner.args.get("offset"):
                    inner.set("order", None)
                    transformed = True
                    diff_note = "Removed redundant ORDER BY inside IN subquery lacking LIMIT."
                    break

        return new_ast, transformed, diff_note

    @classmethod
    def transform_left_to_inner_join(cls, ast: exp.Expression) -> tuple[exp.Expression, bool, str | None]:
        """Converts LEFT JOIN to INNER JOIN when the WHERE clause strictly rejects NULLs on the right table.

        Example:
            SELECT ... FROM customers c LEFT JOIN orders o ON c.id = o.customer_id WHERE o.status = 'delivered'
            ->
            SELECT ... FROM customers c JOIN orders o ON c.id = o.customer_id WHERE o.status = 'delivered'
        Benefit:
            Allows the query planner to reorder tables and choose hash/merge join strategies.
        """
        transformed = False
        diff_note = None
        new_ast = ast.copy()

        where = new_ast.find(exp.Where)
        if not where:
            return new_ast, False, None

        # If WHERE contains OR, IS NULL, or COALESCE, do not convert LEFT JOIN blindly
        if where.find(exp.Or) or where.find(exp.Is) or where.find(exp.Coalesce):
            return new_ast, False, None

        strict_pred_types = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.In)
        null_rejecting_tables: set[str] = set()
        for pred in where.find_all(*strict_pred_types):
            for col in pred.find_all(exp.Column):
                if col.table:
                    null_rejecting_tables.add(col.table.lower())

        for join in new_ast.find_all(exp.Join):
            # Check if this is a LEFT join
            side = join.args.get("side")
            if side and side.upper() == "LEFT":
                table_alias = (join.this.alias or join.this.name).lower()
                if table_alias in null_rejecting_tables:
                    join.set("side", None)  # Strips LEFT -> becomes standard INNER JOIN
                    transformed = True
                    diff_note = f"Converted LEFT JOIN on '{table_alias}' to INNER JOIN due to null-rejecting WHERE predicate."
                    break

        return new_ast, transformed, diff_note

    @classmethod
    def transform_redundant_distinct(cls, ast: exp.Expression) -> tuple[exp.Expression, bool, str | None]:
        """Eliminates redundant DISTINCT when query already has GROUP BY and all GROUP BY keys are projected.

        Example:
            SELECT DISTINCT c.id, COUNT(o.id) FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id
            ->
            SELECT c.id, COUNT(o.id) FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id
        Benefit:
            Eliminates redundant sorting or hashing pass after aggregation.
        """
        transformed = False
        diff_note = None
        new_ast = ast.copy()

        group = new_ast.args.get("group")
        if new_ast.args.get("distinct") and group:
            group_exprs = {g.sql(dialect="postgres").lower() for g in group.expressions}
            select_cols = {
                c.sql(dialect="postgres").lower()
                for s in new_ast.expressions
                for c in ([s.this] if isinstance(s, exp.Alias) else [s])
            }
            if group_exprs and group_exprs.issubset(select_cols):
                new_ast.set("distinct", None)
                transformed = True
                diff_note = "Eliminated redundant DISTINCT on aggregated query with matching GROUP BY."

        return new_ast, transformed, diff_note

    def transform(
        self, sql: str
    ) -> tuple[str, TransformationType, str | None, str | None, str | None]:
        """Runs the conservative AST transformation pipeline on a SQL string."""
        ast = sqlglot.parse_one(sql.strip().rstrip(";"), read="postgres")

        pipeline = [
            (
                TransformationType.REDUNDANT_DISTINCT_ELIMINATION,
                self.transform_redundant_distinct,
                "Redundant DISTINCT eliminated on GROUP BY query",
                "Removes unneeded unique sort or hash aggregate pass",
            ),
            (
                TransformationType.OR_TO_IN_LIST,
                self.transform_or_to_in,
                "Chained OR equality transformed to IN list",
                "Allows PostgreSQL optimizer to use array index scans and bitmap scans",
            ),
            (
                TransformationType.EXISTS_SELECT_ONE_SIMPLIFICATION,
                self.transform_exists_select_one,
                "EXISTS subquery projected columns replaced with constant 1",
                "Reduces tuple formation overhead inside EXISTS subquery",
            ),
            (
                TransformationType.IN_SUBQUERY_ORDER_BY_ELIMINATION,
                self.transform_in_subquery_order_by,
                "Redundant ORDER BY stripped from unconstrained IN subquery",
                "Eliminates sorting overhead in subquery evaluation",
            ),
            (
                TransformationType.LEFT_JOIN_TO_INNER_JOIN,
                self.transform_left_to_inner_join,
                "LEFT JOIN converted to INNER JOIN due to null-rejecting WHERE predicate",
                "Enables join reordering, index nested loops, and hash joins",
            ),
        ]

        for trans_type, fn, reason, benefit in pipeline:
            new_ast, transformed, diff = fn(ast)
            if transformed:
                return new_ast.sql(dialect="postgres"), trans_type, diff, reason, benefit

        return sql, TransformationType.NO_OP, None, "No conservative transformation applicable.", None

