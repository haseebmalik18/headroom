-- catalog-service schema and seed data.

CREATE TABLE categories (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL
);

CREATE TABLE products (
    id           INTEGER PRIMARY KEY,
    category_id  INTEGER NOT NULL REFERENCES categories (id),
    name         TEXT    NOT NULL,
    price_cents  INTEGER NOT NULL
);

CREATE INDEX products_category_idx ON products (category_id);

CREATE TABLE reviews (
    id          BIGSERIAL PRIMARY KEY,
    product_id  INTEGER  NOT NULL REFERENCES products (id),
    rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    body        TEXT     NOT NULL DEFAULT ''
);

CREATE INDEX reviews_product_idx ON reviews (product_id);

CREATE TABLE inventory (
    product_id  INTEGER PRIMARY KEY REFERENCES products (id),
    stock       INTEGER NOT NULL
);

-- 50 categories x 40 products. Deterministic pseudo-random data.
SELECT setseed(0.42);

INSERT INTO categories (id, name)
SELECT i, format('Category %s', i) FROM generate_series(1, 50) AS i;

INSERT INTO products (id, category_id, name, price_cents)
SELECT i, 1 + (i - 1) / 40, format('Product %s', lpad(i::text, 4, '0')), 199 + (i * 7919) % 20000
FROM generate_series(1, 2000) AS i;

-- 0 to 30 reviews per product; about 1 in 6 products has none.
INSERT INTO reviews (product_id, rating, body)
SELECT p.id, 1 + floor(random() * 5)::int, 'Seeded review'
FROM products p
CROSS JOIN LATERAL generate_series(1, floor(random() * 37 + p.id * 0)::int - 6) AS r;

INSERT INTO inventory (product_id, stock)
SELECT id, CASE WHEN id % 9 = 0 THEN 0 ELSE (id * 31) % 500 + 1 END FROM products;
