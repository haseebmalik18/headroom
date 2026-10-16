import os

import asyncpg
import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://catalog:catalog@localhost:5432/catalog")

TEST_CATEGORY = 9001


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
async def test_category(db):
    """A category with hand-picked products, reviews and stock levels."""
    await _cleanup(db)
    await db.execute("INSERT INTO categories (id, name) VALUES ($1, 'Test category')", TEST_CATEGORY)
    products = [
        # id, name, price, ratings, stock
        (900101, "Banana stand", 1500, [5, 4, 3], 12),
        (900102, "Anchor", 999, [], 3),            # no reviews at all
        (900103, "Cactus", 2500, [1, 2], 0),       # out of stock
        (900104, "Drum", 4200, [5, 5, 5, 4], 7),
    ]
    for pid, name, price, ratings, stock in products:
        await db.execute("INSERT INTO products (id, category_id, name, price_cents) VALUES ($1, $2, $3, $4)",
                         pid, TEST_CATEGORY, name, price)
        for rating in ratings:
            await db.execute("INSERT INTO reviews (product_id, rating) VALUES ($1, $2)", pid, rating)
        await db.execute("INSERT INTO inventory (product_id, stock) VALUES ($1, $2)", pid, stock)
    yield TEST_CATEGORY
    await _cleanup(db)


async def _cleanup(db):
    ids = "SELECT id FROM products WHERE category_id = $1"
    await db.execute(f"DELETE FROM reviews WHERE product_id IN ({ids})", TEST_CATEGORY)
    await db.execute(f"DELETE FROM inventory WHERE product_id IN ({ids})", TEST_CATEGORY)
    await db.execute("DELETE FROM products WHERE category_id = $1", TEST_CATEGORY)
    await db.execute("DELETE FROM categories WHERE id IN ($1, $2)", TEST_CATEGORY, TEST_CATEGORY + 1)
