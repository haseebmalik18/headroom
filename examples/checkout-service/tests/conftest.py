"""Black-box tests against a running checkout-service.

BASE_URL points at the service, DATABASE_URL at its database (used only to
create isolated test products and to assert on persisted state).
"""

import os
import uuid

import asyncpg
import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://checkout:checkout@localhost:5432/checkout")


@pytest.fixture
async def client():
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30, limits=limits) as c:
        yield c


@pytest.fixture
async def db():
    conn = await asyncpg.connect(DATABASE_URL)
    yield conn
    await conn.close()


@pytest.fixture
async def make_product(db):
    """Create a product with a unique SKU; deleted (with its reservations) afterwards."""
    created = []

    async def _make(stock: int, price_cents: int = 1000) -> str:
        sku = f"TEST-{uuid.uuid4().hex[:12]}"
        await db.execute(
            "INSERT INTO products (sku, name, price_cents, stock) VALUES ($1, $2, $3, $4)",
            sku,
            f"Test product {sku}",
            price_cents,
            stock,
        )
        created.append(sku)
        return sku

    yield _make

    for sku in created:
        await db.execute("DELETE FROM inventory_events WHERE sku = $1", sku)
        await db.execute(
            "DELETE FROM orders WHERE reservation_id IN (SELECT id FROM reservations WHERE sku = $1)", sku
        )
        await db.execute("DELETE FROM reservations WHERE sku = $1", sku)
        await db.execute("DELETE FROM products WHERE sku = $1", sku)
