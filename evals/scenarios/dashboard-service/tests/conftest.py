import os

import asyncpg
import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://dashboard:dashboard@localhost:5432/dashboard")

TEST_STORE = 999
TEST_CUSTOMERS = (990001, 990002)


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
async def test_store(db):
    """An isolated store with a few hand-made orders and tickets."""
    await _cleanup(db)
    await db.execute("INSERT INTO stores (id, name) VALUES ($1, 'Test store')", TEST_STORE)
    for cid in TEST_CUSTOMERS:
        await db.execute("INSERT INTO customers (id, store_id, created_at) VALUES ($1, $2, now())", cid, TEST_STORE)
    orders = [
        # customer, status, total, days ago, items [(product, qty)]
        (990001, "paid", 1000, 1, [(1, 2), (2, 1)]),
        (990001, "paid", 2500, 3, [(1, 1)]),
        (990002, "paid", 4000, 10, [(3, 5)]),
        (990002, "refunded", 9999, 2, [(4, 9)]),     # refunds never count
        (990002, "paid", 7777, 45, [(5, 9)]),        # older than 30 days
    ]
    for customer, status, total, days, items in orders:
        order_id = await db.fetchval(
            "INSERT INTO orders (store_id, customer_id, status, total_cents, created_at) "
            "VALUES ($1, $2, $3, $4, now() - make_interval(days => $5)) RETURNING id",
            TEST_STORE, customer, status, total, days,
        )
        for product, qty in items:
            await db.execute("INSERT INTO order_items (order_id, product_id, quantity, price_cents) "
                             "VALUES ($1, $2, $3, 100)", order_id, product, qty)
    await db.execute("INSERT INTO tickets (store_id, status, created_at) VALUES ($1, 'open', now()), "
                     "($1, 'open', now()), ($1, 'closed', now())", TEST_STORE)
    yield TEST_STORE
    await _cleanup(db)


async def _cleanup(db):
    await db.execute("DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE store_id = $1)",
                     TEST_STORE)
    await db.execute("DELETE FROM orders WHERE store_id = $1", TEST_STORE)
    await db.execute("DELETE FROM tickets WHERE store_id = $1", TEST_STORE)
    await db.execute("DELETE FROM customers WHERE store_id = $1", TEST_STORE)
    await db.execute("DELETE FROM stores WHERE id = $1", TEST_STORE)
