-- checkout-service schema and seed data.
-- Loaded automatically by the postgres image on first start.

CREATE TABLE products (
    sku          TEXT PRIMARY KEY,
    name         TEXT        NOT NULL,
    price_cents  INTEGER     NOT NULL,
    stock        INTEGER     NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reservations (
    id                BIGSERIAL PRIMARY KEY,
    sku               TEXT        NOT NULL REFERENCES products (sku),
    quantity          INTEGER     NOT NULL,
    unit_price_cents  INTEGER     NOT NULL,
    status            TEXT        NOT NULL DEFAULT 'held',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX reservations_sku_idx ON reservations (sku);

-- Append-only audit trail of every stock movement.
CREATE TABLE inventory_events (
    id              BIGSERIAL PRIMARY KEY,
    sku             TEXT        NOT NULL REFERENCES products (sku),
    delta           INTEGER     NOT NULL,
    stock_after     INTEGER     NOT NULL,
    reason          TEXT        NOT NULL,
    reservation_id  BIGINT      REFERENCES reservations (id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    id              BIGSERIAL PRIMARY KEY,
    reservation_id  BIGINT      NOT NULL UNIQUE REFERENCES reservations (id),
    total_cents     INTEGER     NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 1,000 catalog products with deep stock so load tests never run dry.
INSERT INTO products (sku, name, price_cents, stock)
SELECT format('SKU-%s', lpad(i::text, 5, '0')),
       format('Product %s', i),
       500 + (i * 37) % 9500,
       1000000
FROM generate_series(1, 1000) AS i;
