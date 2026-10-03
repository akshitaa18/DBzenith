-- =============================================================================
-- DBZenith E-Commerce Sample Database Schema & Official Benchmark Dataset
--
-- Tables:
--   1. regions   (region_id, region_name, country)
--   2. customers (customer_id, first_name, last_name, email, phone, address, region_id, created_at)
--   3. products  (product_id, product_name, category, price, stock_quantity, created_at)
--   4. orders    (order_id, customer_id, product_id, region_id, order_date, quantity, amount, status, created_at)
-- =============================================================================

-- 1. REGIONS TABLE
CREATE TABLE IF NOT EXISTS regions (
    region_id SERIAL PRIMARY KEY,
    region_name VARCHAR(100) NOT NULL,
    country VARCHAR(100) NOT NULL
);

-- 2. PRODUCTS TABLE
CREATE TABLE IF NOT EXISTS products (
    product_id SERIAL PRIMARY KEY,
    product_name VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL,
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. CUSTOMERS TABLE
CREATE TABLE IF NOT EXISTS customers (
    customer_id SERIAL PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(50),
    address VARCHAR(255),
    region_id INTEGER REFERENCES regions(region_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 4. ORDERS TABLE
CREATE TABLE IF NOT EXISTS orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    region_id INTEGER REFERENCES regions(region_id) ON DELETE SET NULL,
    order_date DATE NOT NULL DEFAULT CURRENT_DATE,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    amount NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- Performance & Telemetry Indexes
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_customers_region_id ON customers(region_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_product_id ON orders(product_id);
CREATE INDEX IF NOT EXISTS idx_orders_region_id ON orders(region_id);
CREATE INDEX IF NOT EXISTS idx_orders_status_date ON orders(status, order_date);

-- =============================================================================
-- POPULATE REGIONS
-- =============================================================================
INSERT INTO regions (region_id, region_name, country) VALUES
    (1, 'North America - East', 'United States'),
    (2, 'North America - West', 'United States'),
    (3, 'Europe - Central', 'Germany'),
    (4, 'Europe - West', 'United Kingdom'),
    (5, 'Asia Pacific - South', 'India'),
    (6, 'Asia Pacific - East', 'Japan'),
    (7, 'Latin America', 'Brazil'),
    (8, 'Australia & Oceania', 'Australia')
ON CONFLICT (region_id) DO NOTHING;

SELECT setval('regions_region_id_seq', (SELECT COALESCE(MAX(region_id), 1) FROM regions));

-- =============================================================================
-- POPULATE PRODUCTS
-- =============================================================================
INSERT INTO products (product_id, product_name, category, price, stock_quantity, created_at) VALUES
    (1, 'Ergonomic Mechanical Keyboard', 'Electronics', 129.99, 150, NOW() - INTERVAL '180 days'),
    (2, 'Ultra-Wide 34-inch Monitor', 'Electronics', 499.50, 45, NOW() - INTERVAL '150 days'),
    (3, 'Wireless Noise-Canceling Headphones', 'Audio', 249.00, 80, NOW() - INTERVAL '120 days'),
    (4, 'USB-C Dual 4K Docking Station', 'Accessories', 179.99, 200, NOW() - INTERVAL '90 days'),
    (5, 'Standing Desk Converter 36-inch', 'Office Furniture', 219.00, 30, NOW() - INTERVAL '75 days'),
    (6, 'High-Precision Wireless Mouse', 'Electronics', 79.95, 300, NOW() - INTERVAL '60 days'),
    (7, 'Smart LED Desk Lamp', 'Lighting', 45.00, 110, NOW() - INTERVAL '45 days'),
    (8, 'Aluminum Laptop Stand', 'Accessories', 39.99, 250, NOW() - INTERVAL '30 days'),
    (9, 'Webcam 4K Ultra HD Pro', 'Electronics', 119.00, 95, NOW() - INTERVAL '20 days'),
    (10, 'Leather Ergonomic Office Chair', 'Office Furniture', 389.00, 20, NOW() - INTERVAL '10 days')
ON CONFLICT (product_id) DO NOTHING;

SELECT setval('products_product_id_seq', (SELECT COALESCE(MAX(product_id), 1) FROM products));

-- =============================================================================
-- POPULATE CUSTOMERS
-- =============================================================================
INSERT INTO customers (customer_id, first_name, last_name, email, phone, address, region_id, created_at) VALUES
    (1, 'Emma', 'Watson', 'emma.watson@example.com', '+1-555-0101', '742 Evergreen Terrace, Seattle, WA', 2, NOW() - INTERVAL '200 days'),
    (2, 'Liam', 'Miller', 'liam.miller@example.com', '+1-555-0102', '120 Broadway Ave, New York, NY', 1, NOW() - INTERVAL '190 days'),
    (3, 'Sophia', 'Schmidt', 'sophia.schmidt@example.de', '+49-30-123456', 'Friedrichstrasse 44, Berlin', 3, NOW() - INTERVAL '180 days'),
    (4, 'Oliver', 'Smith', 'oliver.smith@example.co.uk', '+44-20-794609', '10 Downing St, London', 4, NOW() - INTERVAL '160 days'),
    (5, 'Aarav', 'Patel', 'aarav.patel@example.in', '+91-98765-43210', 'MG Road, Bangalore', 5, NOW() - INTERVAL '140 days'),
    (6, 'Kenji', 'Takahashi', 'kenji.takahashi@example.jp', '+81-3-5555-0143', 'Shibuya 2-Chome, Tokyo', 6, NOW() - INTERVAL '120 days'),
    (7, 'Mariana', 'Silva', 'mariana.silva@example.br', '+55-11-98765-4321', 'Av. Paulista 1000, Sao Paulo', 7, NOW() - INTERVAL '100 days'),
    (8, 'Jack', 'Taylor', 'jack.taylor@example.au', '+61-2-9876-5432', 'George Street, Sydney', 8, NOW() - INTERVAL '80 days'),
    (9, 'Chloe', 'Dubois', 'chloe.dubois@example.fr', '+33-1-4268-5555', 'Rue de Rivoli, Paris', 4, NOW() - INTERVAL '60 days'),
    (10, 'Noah', 'Davis', 'noah.davis@example.com', '+1-555-0199', 'Market Street, San Francisco, CA', 2, NOW() - INTERVAL '40 days')
ON CONFLICT (customer_id) DO NOTHING;

SELECT setval('customers_customer_id_seq', (SELECT COALESCE(MAX(customer_id), 1) FROM customers));

-- =============================================================================
-- POPULATE ORDERS
-- =============================================================================
INSERT INTO orders (order_id, customer_id, product_id, region_id, order_date, quantity, amount, status, created_at) VALUES
    (1, 1, 2, 2, CURRENT_DATE - INTERVAL '120 days', 1, 499.50, 'delivered', NOW() - INTERVAL '120 days'),
    (2, 2, 1, 1, CURRENT_DATE - INTERVAL '110 days', 2, 259.98, 'delivered', NOW() - INTERVAL '110 days'),
    (3, 3, 3, 3, CURRENT_DATE - INTERVAL '95 days', 1, 249.00, 'delivered', NOW() - INTERVAL '95 days'),
    (4, 4, 4, 4, CURRENT_DATE - INTERVAL '80 days', 1, 179.99, 'delivered', NOW() - INTERVAL '80 days'),
    (5, 5, 6, 5, CURRENT_DATE - INTERVAL '65 days', 3, 239.85, 'delivered', NOW() - INTERVAL '65 days'),
    (6, 6, 9, 6, CURRENT_DATE - INTERVAL '50 days', 1, 119.00, 'shipped', NOW() - INTERVAL '50 days'),
    (7, 7, 5, 7, CURRENT_DATE - INTERVAL '40 days', 1, 219.00, 'shipped', NOW() - INTERVAL '40 days'),
    (8, 8, 8, 8, CURRENT_DATE - INTERVAL '25 days', 2, 79.98, 'processing', NOW() - INTERVAL '25 days'),
    (9, 9, 7, 4, CURRENT_DATE - INTERVAL '15 days', 2, 90.00, 'processing', NOW() - INTERVAL '15 days'),
    (10, 10, 10, 2, CURRENT_DATE - INTERVAL '5 days', 1, 389.00, 'pending', NOW() - INTERVAL '5 days'),
    (11, 1, 6, 2, CURRENT_DATE - INTERVAL '3 days', 1, 79.95, 'pending', NOW() - INTERVAL '3 days'),
    (12, 3, 1, 3, CURRENT_DATE - INTERVAL '1 days', 1, 129.99, 'pending', NOW() - INTERVAL '1 days')
ON CONFLICT (order_id) DO NOTHING;

SELECT setval('orders_order_id_seq', (SELECT COALESCE(MAX(order_id), 1) FROM orders));

-- =============================================================================
-- SCALABLE SYNTHETIC BATCH (1,000 realistic orders for query plan telemetry)
-- =============================================================================
INSERT INTO orders (customer_id, product_id, region_id, order_date, quantity, amount, status, created_at)
SELECT
    ((g % 10) + 1) AS customer_id,
    ((g % 10) + 1) AS product_id,
    (((g * 3) % 8) + 1) AS region_id,
    CURRENT_DATE - ((g % 90) || ' days')::INTERVAL AS order_date,
    ((g % 4) + 1) AS quantity,
    ROUND((((g % 4) + 1) * (((g * 37) % 300) + 25.50))::numeric, 2) AS amount,
    CASE 
        WHEN g % 10 < 6 THEN 'delivered'
        WHEN g % 10 < 8 THEN 'shipped'
        WHEN g % 10 < 9 THEN 'processing'
        ELSE 'pending'
    END AS status,
    NOW() - ((g % 90) || ' days')::INTERVAL AS created_at
FROM generate_series(13, 1012) AS g;

-- ANALYZE TABLES FOR POSTGRESQL QUERY PLANNER OPTIMIZATION
ANALYZE regions;
ANALYZE products;
ANALYZE customers;
ANALYZE orders;
