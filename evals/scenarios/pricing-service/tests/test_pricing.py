import asyncio
import time

# 168 units in the week is 1 per hour on average; 4 in the last hour is 4x that,
# so the multiplier is 1 + 0.25 * (4 - 1) = 1.75, capped at 1.5.


async def test_health(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_price_follows_demand(client, product):
    q = (await client.get(f"/products/{product}/price")).json()

    assert q == {"sku": product, "price_cents": 15000, "base_price_cents": 10000,
                 "demand_multiplier": 1.5, "low_stock": False}


async def test_quiet_product_is_discounted(client, db, product):
    await db.execute("DELETE FROM order_lines WHERE sku = $1 AND ordered_at > now() - interval '1 hour'", product)

    q = (await client.get(f"/products/{product}/price")).json()

    assert q["demand_multiplier"] == 0.9
    assert q["price_cents"] == 9000


async def test_low_stock_adds_ten_percent(client, db, product):
    await db.execute("UPDATE products SET stock = 5 WHERE sku = $1", product)

    q = (await client.get(f"/products/{product}/price")).json()

    assert q["low_stock"] is True
    assert q["price_cents"] == 16500


async def test_unknown_product_returns_404(client):
    assert (await client.get("/products/NO-SUCH-SKU/price")).status_code == 404


async def _price_within(client, sku, expected, seconds):
    deadline = time.monotonic() + seconds
    seen = None
    while time.monotonic() < deadline:
        seen = (await client.get(f"/products/{sku}/price")).json()["price_cents"]
        if seen == expected:
            return True
        await asyncio.sleep(0.1)
    return seen == expected


async def test_base_price_change_shows_within_three_seconds(client, db, product):
    assert (await client.get(f"/products/{product}/price")).json()["price_cents"] == 15000
    await db.execute("UPDATE products SET base_price_cents = 20000 WHERE sku = $1", product)

    assert await _price_within(client, product, 30000, seconds=3.0)


async def test_new_demand_shows_within_three_seconds(client, db, product):
    await db.execute("DELETE FROM order_lines WHERE sku = $1 AND ordered_at > now() - interval '1 hour'", product)
    assert (await client.get(f"/products/{product}/price")).json()["price_cents"] == 9000
    await db.execute("INSERT INTO order_lines (sku, quantity, ordered_at) VALUES ($1, 4, now())", product)

    assert await _price_within(client, product, 15000, seconds=3.0)


async def test_concurrent_requests_agree(client, product):
    quotes = await asyncio.gather(*(client.get(f"/products/{product}/price") for _ in range(50)))

    assert {q.json()["price_cents"] for q in quotes} == {15000}
