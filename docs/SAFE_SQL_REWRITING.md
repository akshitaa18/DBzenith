# DBZenith Safe SQL Rewriting Subsystem

## Overview
DBZenith provides an autonomous, AST-driven, safe SQL query rewriting engine designed to optimize queries without altering semantic results or risking regressions.

```
Candidate SQL
      │
      ▼
┌───────────────────────────────┐
│   SQLRewriteSafetyPolicy      │  ---> Rejects DML, DDL, Volatile Functions,
└──────────────┬────────────────┘       Altered Projection Arity
               │ (Safe)
               ▼
┌───────────────────────────────┐
│      SQLASTTransformer        │  ---> Conservative AST transformations via sqlglot
└──────────────┬────────────────┘
               │ (Candidate Rewrite)
               ▼
┌───────────────────────────────┐
│    SandboxRewriteValidator    │  ---> Isolated Sandbox Simulation:
└──────────────┬────────────────┘       - EXPLAIN (Total Cost delta)
               │                        - Semantic regression test (multiset hashing)
               ▼
┌───────────────────────────────┐
│       SQLRewriteResult        │  ---> Complete 7-tuple contract
└──────────────┬────────────────┘
               │
      ┌────────┴────────┐
      ▼                 ▼
QueryRewriteAdvisor    RL Engine (ActionType.REWRITE_QUERY)
```

---

## 7 Mandatory Rewrite Attributes

Every rewrite produced by DBZenith strictly contains:

1. **`original_query`**: The exact original SQL input.
2. **`rewritten_query`**: The AST-transformed SQL candidate.
3. **`transformation`**: The specific transformation type applied (e.g., `OR_TO_IN_LIST`, `EXISTS_SELECT_ONE_SIMPLIFICATION`).
4. **`reason`**: Technical rationale explaining why the rewrite is advantageous.
5. **`expected_benefit`**: Anticipated optimizer or execution advantage.
6. **`confidence`**: Statistical / heuristic confidence score ($0.0 \dots 1.0$).
7. **`validation_status`**: Current sandbox validation state (`pending`, `validated_in_sandbox`, `rejected_semantic_regression`, `unsafe_rejected`, `cost_regression_rejected`).

---

## Strict Production Safety Invariant

> [!IMPORTANT]
> **Production Mutation Invariant**: Under no circumstance is production SQL or the production database modified directly.
> Every rewrite requires DBA approval (`requires_approval = True`) and must pass sandbox regression validation prior to recommendation. `production_modified` is strictly hardcoded to `False`.

---

## Conservative Transformations Implemented

1. **`OR_TO_IN_LIST`**:
   - Converts chained equality OR expressions on the same attribute (`WHERE col = 1 OR col = 2 OR col = 3`) into an `IN` list (`WHERE col IN (1, 2, 3)`).
   - *Benefit*: Enables PostgreSQL to utilize array index scans and bitmap index scans instead of tree-walk evaluation.
2. **`EXISTS_SELECT_ONE_SIMPLIFICATION`**:
   - Rewrites `WHERE EXISTS (SELECT * ...)` to `WHERE EXISTS (SELECT 1 ...)`.
   - *Benefit*: Eliminates tuple formation and row width overhead within the subquery.
3. **`IN_SUBQUERY_ORDER_BY_ELIMINATION`**:
   - Strips redundant `ORDER BY` clauses from unconstrained `IN (SELECT ...)` subqueries lacking `LIMIT` or `OFFSET`.
   - *Benefit*: Bypasses unnecessary in-memory / temp-block sorting.
4. **`LEFT_JOIN_TO_INNER_JOIN`**:
   - Converts `LEFT JOIN` into `INNER JOIN` when the outer `WHERE` clause strictly filters out NULL values on the right-hand relation.
   - *Benefit*: Unlocks join reordering, index nested loops, and hash joins for the planner.
5. **`REDUNDANT_DISTINCT_ELIMINATION`**:
   - Strips `DISTINCT` when a query already performs a matching `GROUP BY` that guarantees uniqueness.
   - *Benefit*: Removes secondary unique sort or hash-aggregate pass.

---

## Safety Policy & Rejection Rules

The `SQLRewriteSafetyPolicy` automatically rejects queries that violate database safety:
- **DML Mutations**: Rejects `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`.
- **DDL Mutations**: Rejects `DROP`, `CREATE`, `ALTER`, `GRANT`, `REVOKE`.
- **Volatile / Non-deterministic Functions**: Rejects `random()`, `gen_random_uuid()`, `clock_timestamp()`, `timeofday()`, `statement_timestamp()`, `nextval()`, `txid_current()`.
- **Outer Projection Alterations**: Verifies column count between original and rewritten query matches.
- **Limit/Offset Divergence**: Rejects transformations that strip or alter client-specified limits.

---

## Sandbox Validation & Semantic Regression Verification

- **Planner Cost Evaluation**: Runs `EXPLAIN (FORMAT JSON)` on both queries in the sandbox to measure total cost change (`cost_improvement_pct`). Any transformation with $<-5\%$ cost regression is rejected.
- **Multiset Tuple Equivalence**: Executes a bounded sample (`LIMIT 200`) in the isolated sandbox, sorting and hashing row tuples. If row counts or row content differ in any way, the rewrite is tagged as `rejected_semantic_regression`.

---

## Integration with Recommendations & Reinforcement Learning

- **Recommendation System (`QueryRewriteAdvisor`)**: Inspects query telemetry and automatically generates typed `OptimizationRecommendation` records with all 7 fields embedded in the `evidence` payload.
- **Reinforcement Learning (`ActionType.REWRITE_QUERY`)**: The Gymnasium RL optimization engine invokes the `SQLRewriteEngine` during action synthesis and evaluates the reward based on empirical sandbox measurements.
- **REST API**:
  - `POST /api/v1/rewriter/rewrite` accepts `{"sql": "...", "validate_sandbox": true}` and returns the complete `SQLRewriteResult`.
