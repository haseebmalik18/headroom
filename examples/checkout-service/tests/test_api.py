async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_list_products_returns_seeded_catalog(client):
    response = await client.get("/products", params={"limit": 5})
    assert response.status_code == 200
    products = response.json()
    assert len(products) == 5
    assert {"sku", "name", "price_cents", "stock"} <= products[0].keys()


async def test_reserve_decrements_stock(client, db, make_product):
    sku = await make_product(stock=10, price_cents=2500)

    response = await client.post("/inventory/reserve", json={"sku": sku, "quantity": 3})

    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == sku
    assert body["quantity"] == 3
    assert body["unit_price_cents"] == 2500
    assert body["remaining_stock"] == 7
    assert await db.fetchval("SELECT stock FROM products WHERE sku = $1", sku) == 7
    status = await db.fetchval("SELECT status FROM reservations WHERE id = $1", body["reservation_id"])
    assert status == "held"


async def test_reserve_records_inventory_event(client, db, make_product):
    sku = await make_product(stock=10)

    body = (await client.post("/inventory/reserve", json={"sku": sku, "quantity": 2})).json()

    event = await db.fetchrow(
        "SELECT delta, stock_after, reason FROM inventory_events WHERE reservation_id = $1",
        body["reservation_id"],
    )
    assert dict(event) == {"delta": -2, "stock_after": 8, "reason": "reserve"}


async def test_reserve_unknown_sku_returns_404(client):
    response = await client.post("/inventory/reserve", json={"sku": "NOPE-0", "quantity": 1})
    assert response.status_code == 404


async def test_reserve_more_than_available_returns_409(client, db, make_product):
    sku = await make_product(stock=2)

    response = await client.post("/inventory/reserve", json={"sku": sku, "quantity": 3})

    assert response.status_code == 409
    assert await db.fetchval("SELECT stock FROM products WHERE sku = $1", sku) == 2
    assert await db.fetchval("SELECT count(*) FROM reservations WHERE sku = $1", sku) == 0


async def test_reserve_rejects_non_positive_quantity(client, make_product):
    sku = await make_product(stock=5)
    response = await client.post("/inventory/reserve", json={"sku": sku, "quantity": 0})
    assert response.status_code == 422


async def test_reserve_exact_remaining_stock_succeeds(client, db, make_product):
    sku = await make_product(stock=4)

    response = await client.post("/inventory/reserve", json={"sku": sku, "quantity": 4})

    assert response.status_code == 201
    assert response.json()["remaining_stock"] == 0
    assert await db.fetchval("SELECT stock FROM products WHERE sku = $1", sku) == 0


async def test_checkout_creates_order_and_confirms_reservation(client, db, make_product):
    sku = await make_product(stock=10, price_cents=1250)
    reservation = (await client.post("/inventory/reserve", json={"sku": sku, "quantity": 2})).json()

    response = await client.post("/checkout", json={"reservation_id": reservation["reservation_id"]})

    assert response.status_code == 201
    order = response.json()
    assert order["reservation_id"] == reservation["reservation_id"]
    assert order["total_cents"] == 2500
    status = await db.fetchval("SELECT status FROM reservations WHERE id = $1", reservation["reservation_id"])
    assert status == "confirmed"


async def test_checkout_twice_returns_409(client, make_product):
    sku = await make_product(stock=10)
    reservation = (await client.post("/inventory/reserve", json={"sku": sku, "quantity": 1})).json()
    first = await client.post("/checkout", json={"reservation_id": reservation["reservation_id"]})
    assert first.status_code == 201

    second = await client.post("/checkout", json={"reservation_id": reservation["reservation_id"]})

    assert second.status_code == 409


async def test_checkout_unknown_reservation_returns_404(client):
    response = await client.post("/checkout", json={"reservation_id": 999_999_999})
    assert response.status_code == 404
