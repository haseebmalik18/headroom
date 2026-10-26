-- dashboard-service schema and seed data (deterministic, relative to init time).

CREATE TABLE stores (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL
);

CREATE TABLE products (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL
);

CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    store_id    INTEGER NOT NULL REFERENCES stores (id),
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE orders (
    id           BIGSERIAL PRIMARY KEY,
    store_id     INTEGER     NOT NULL REFERENCES stores (id),
    customer_id  INTEGER     NOT NULL REFERENCES customers (id),
    status       TEXT        NOT NULL,
    total_cents  INTEGER     NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE order_items (
    order_id     BIGINT  NOT NULL REFERENCES orders (id),
    product_id   INTEGER NOT NULL REFERENCES products (id),
    quantity     INTEGER NOT NULL,
    price_cents  INTEGER NOT NULL
);

CREATE TABLE tickets (
    id          BIGSERIAL PRIMARY KEY,
    store_id    INTEGER     NOT NULL REFERENCES stores (id),
    status      TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);

SELECT setseed(0.7);

INSERT INTO stores SELECT i, format('Store %s', i) FROM generate_series(1, 200) AS i;
INSERT INTO products SELECT i, format('Product %s', i) FROM generate_series(1, 500) AS i;

INSERT INTO customers (id, store_id, created_at)
SELECT i, 1 + (i % 200), now() - (random() * interval '180 days')
FROM generate_series(1, 60000) AS i;

-- 2,000 orders per store over the last 90 days.
INSERT INTO orders (store_id, customer_id, status, total_cents, created_at)
SELECT 1 + (i % 200),
       1 + (i % 200) + 200 * floor(random() * 299)::int,
       CASE WHEN random() < 0.92 THEN 'paid' ELSE 'refunded' END,
       500 + floor(random() * 20000)::int,
       now() - (random() * interval '90 days')
FROM generate_series(1, 400000) AS i;

INSERT INTO order_items (order_id, product_id, quantity, price_cents)
SELECT o.id, 1 + floor(random() * 500)::int, 1 + floor(random() * 4)::int, 200 + floor(random() * 5000)::int
FROM orders o CROSS JOIN generate_series(1, 3);

INSERT INTO tickets (store_id, status, created_at)
SELECT 1 + (i % 200), CASE WHEN random() < 0.3 THEN 'open' ELSE 'closed' END, now() - (random() * interval '60 days')
FROM generate_series(1, 40000) AS i;

CREATE INDEX orders_store_created_idx ON orders (store_id, created_at);
CREATE INDEX order_items_order_idx ON order_items (order_id);
CREATE INDEX customers_store_created_idx ON customers (store_id, created_at);
CREATE INDEX tickets_store_status_idx ON tickets (store_id, status);

-- Settle the freshly loaded tables (visibility map, statistics) and flush them to disk, so
-- benchmarks measure the service rather than post-load maintenance.
VACUUM ANALYZE;
CHECKPOINT;
