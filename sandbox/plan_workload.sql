-- Real PostgreSQL synthetic queries for DBZenith v0.4 plan analysis.
-- Run after sandbox/workload.sql has created telemetry_demo_orders.

-- Sequential-scan candidate (planner-dependent).
SELECT count(*) FROM telemetry_demo_orders WHERE amount > 10;

-- Index-scan candidate.
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234;

-- Sort + aggregate.
SELECT status, count(*), avg(amount)
FROM telemetry_demo_orders
GROUP BY status
ORDER BY avg(amount) DESC;

-- Join candidate.
SELECT a.customer_id, count(*)
FROM telemetry_demo_orders a
JOIN telemetry_demo_orders b ON b.customer_id = a.customer_id
WHERE a.amount > 700
GROUP BY a.customer_id
ORDER BY count(*) DESC;
