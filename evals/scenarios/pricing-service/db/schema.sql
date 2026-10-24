-- pricing-service schema and seed data.

CREATE TABLE products (
    sku               TEXT    PRIMARY KEY,
    name              TEXT    NOT NULL,
    base_price_cents  INTEGER NOT NULL CHECK (base_price_cents > 0),
    stock             INTEGER NOT NULL CHECK (stock >= 0)
);

CREATE TABLE order_lines (
    id          BIGSERIAL   PRIMARY KEY,
    sku         TEXT        NOT NULL REFERENCES products (sku),
    quantity    INTEGER     NOT NULL CHECK (quantity > 0),
    ordered_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX order_lines_sku_time_idx ON order_lines (sku, ordered_at);

-- 24 products. SKU-01..SKU-05 are this week's bestsellers with a long order history;
-- the rest sell slowly. Deterministic pseudo-random data.
SELECT setseed(0.31);

INSERT INTO products (sku, name, base_price_cents, stock)
SELECT format('SKU-%s', lpad(i::text, 2, '0')),
       format('Product %s', i),
       999 + (i * 7919) % 15000,
       CASE WHEN i % 7 = 0 THEN 8 ELSE 40 + (i * 37) % 400 END
FROM generate_series(1, 24) AS i;

INSERT INTO order_lines (sku, quantity, ordered_at)
SELECT format('SKU-%s', lpad((1 + (n % 5))::text, 2, '0')),
       1 + floor(random() * 3)::int,
       now() - random() * interval '7 days'
FROM generate_series(1, 600000) AS n;

INSERT INTO order_lines (sku, quantity, ordered_at)
SELECT format('SKU-%s', lpad((6 + (n % 19))::text, 2, '0')),
       1 + floor(random() * 3)::int,
       now() - random() * interval '7 days'
FROM generate_series(1, 38000) AS n;

VACUUM ANALYZE;
CHECKPOINT;
