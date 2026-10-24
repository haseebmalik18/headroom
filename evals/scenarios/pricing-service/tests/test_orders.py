import asyncio
import time


async def test_order_takes_stock_and_is_recorded(client, db, product):
    response = await client.post("/orders", json={"sku": product, "quantity": 3})

    assert response.status_code == 201
    assert response.json()["remaining_stock"] == 97
    assert await db.fetchval("SELECT stock FROM products WHERE sku = $1", product) == 97
    assert await db.fetchval("SELECT count(*) FROM order_lines WHERE sku = $1 AND quantity = 3", product) == 1


async def test_order_beyond_stock_is_refused_and_changes_nothing(client, db, product):
    await db.execute("UPDATE products SET stock = 2 WHERE sku = $1", product)

    response = await client.post("/orders", json={"sku": product, "quantity": 3})

    assert response.status_code == 409
    assert await db.fetchval("SELECT stock FROM products WHERE sku = $1", product) == 2


async def test_unknown_product_cannot_be_ordered(client):
    assert (await client.post("/orders", json={"sku": "NO-SUCH-SKU", "quantity": 1})).status_code == 404


async def test_concurrent_orders_never_oversell(client, db, product):
    await db.execute("UPDATE products SET stock = 10 WHERE sku = $1", product)

    responses = await asyncio.gather(*(client.post("/orders", json={"sku": product, "quantity": 1}) for _ in range(30)))

    assert sorted(r.status_code for r in responses).count(201) == 10
    assert await db.fetchval("SELECT stock FROM products WHERE sku = $1", product) == 0


async def test_an_order_shows_in_the_price_within_three_seconds(client, db, product):
    await db.execute("DELETE FROM order_lines WHERE sku = $1 AND ordered_at > now() - interval '1 hour'", product)
    assert (await client.get(f"/products/{product}/price")).json()["price_cents"] == 9000

    assert (await client.post("/orders", json={"sku": product, "quantity": 4})).status_code == 201

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if (await client.get(f"/products/{product}/price")).json()["price_cents"] == 15000:
            return
        await asyncio.sleep(0.1)
    raise AssertionError("the order did not show in the price within 3 seconds")
