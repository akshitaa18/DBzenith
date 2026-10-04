-- DBZenith synthetic development workload.
-- These are real PostgreSQL statements executed against the dev database.
CREATE TABLE IF NOT EXISTS telemetry_demo_orders (
    id BIGSERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    amount NUMERIC(10,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload TEXT
);

CREATE INDEX IF NOT EXISTS idx_telemetry_demo_orders_customer
    ON telemetry_demo_orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_demo_orders_status_created
    ON telemetry_demo_orders(status, created_at);

INSERT INTO telemetry_demo_orders (customer_id, status, amount, created_at, payload)
SELECT
    (g % 5000) + 1,
    CASE WHEN g % 10 < 7 THEN 'completed' WHEN g % 10 < 9 THEN 'pending' ELSE 'cancelled' END,
    ((g * 17) % 100000) / 100.0,
    now() - ((g % 365) || ' days')::interval,
    repeat('order-payload-', (g % 4) + 1)
FROM generate_series(1, 10000) AS g
WHERE NOT EXISTS (SELECT 1 FROM telemetry_demo_orders LIMIT 1);

ANALYZE telemetry_demo_orders;

SELECT id, customer_id, status, amount
FROM telemetry_demo_orders
WHERE customer_id = 1234
ORDER BY created_at DESC
LIMIT 20;

SELECT count(*)
FROM telemetry_demo_orders
WHERE status = 'pending';

SELECT status, count(*), avg(amount)
FROM telemetry_demo_orders
GROUP BY status;

-- Repeated execution produces meaningful pg_stat_statements call counts.
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';

-- A deliberately less selective workload for slow-query detection in development.
SELECT count(*)
FROM telemetry_demo_orders a
JOIN telemetry_demo_orders b
  ON b.customer_id = a.customer_id
WHERE a.amount > 700.00;

SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';
SELECT id, amount FROM telemetry_demo_orders WHERE customer_id = 1234 ORDER BY created_at DESC LIMIT 10;
SELECT count(*) FROM telemetry_demo_orders WHERE status = 'pending';

-- Development-only latency sentinel: a real PostgreSQL statement used to verify slow-query detection.
SELECT pg_sleep(0.15);
