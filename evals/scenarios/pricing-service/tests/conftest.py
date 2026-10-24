import os

import asyncpg
import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://pricing:pricing@localhost:5432/pricing")


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as c:
        yield c


@pytest.fixture
async def db():
    conn = await asyncpg.connect(DATABASE_URL)
    yield conn
    await conn.close()


@pytest.fixture
async def product(db, request):
    """A product with a hand-made order history: 168 units over the week, 4 of them in the last hour."""
    sku = f"TEST-{request.node.name}"  # unique per test, so no test reads another's cached quote
    await _cleanup(db, sku)
    await db.execute("INSERT INTO products (sku, name, base_price_cents, stock) VALUES ($1, 'Test', 10000, 100)", sku)
    await db.execute(
        "INSERT INTO order_lines (sku, quantity, ordered_at) "
        "SELECT $1, 1, now() - interval '2 days' - (n || ' minutes')::interval FROM generate_series(1, 164) AS n",
        sku,
    )
    await db.execute(
        "INSERT INTO order_lines (sku, quantity, ordered_at) "
        "SELECT $1, 1, now() - (n || ' minutes')::interval FROM generate_series(1, 4) AS n",
        sku,
    )
    yield sku
    await _cleanup(db, sku)


async def _cleanup(db, sku):
    await db.execute("DELETE FROM order_lines WHERE sku = $1", sku)
    await db.execute("DELETE FROM products WHERE sku = $1", sku)
