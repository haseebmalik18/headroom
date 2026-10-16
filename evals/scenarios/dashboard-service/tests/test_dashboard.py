async def test_health(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_summary_for_hand_made_store(client, test_store):
    response = await client.get("/dashboard/summary", params={"store_id": test_store})

    assert response.status_code == 200
    s = response.json()
    assert s["revenue_cents"] == 1000 + 2500 + 4000
    assert s["orders"] == 3
    assert s["repeat_customers"] == 1          # 990001 ordered twice in 30 days
    assert s["open_tickets"] == 2
    assert s["top_products"] == [
        {"id": 3, "name": "Product 3", "units": 5},
        {"id": 1, "name": "Product 1", "units": 3},
        {"id": 2, "name": "Product 2", "units": 1},
    ]
    assert sum(d["revenue_cents"] for d in s["daily_revenue"]) == s["revenue_cents"]


async def test_new_order_is_reflected_immediately(client, db, test_store):
    before = (await client.get("/dashboard/summary", params={"store_id": test_store})).json()
    await db.execute(
        "INSERT INTO orders (store_id, customer_id, status, total_cents, created_at) "
        "VALUES ($1, 990002, 'paid', 1234, now())", test_store,
    )

    after = (await client.get("/dashboard/summary", params={"store_id": test_store})).json()

    assert after["revenue_cents"] == before["revenue_cents"] + 1234
    assert after["orders"] == before["orders"] + 1
    assert after["repeat_customers"] == before["repeat_customers"] + 1


async def test_seeded_store_matches_database(client, db):
    s = (await client.get("/dashboard/summary", params={"store_id": 4})).json()

    rows = await db.fetch(
        "SELECT customer_id, total_cents FROM orders "
        "WHERE store_id = 4 AND status = 'paid' AND created_at >= now() - interval '30 days'"
    )
    per_customer: dict[int, int] = {}
    for row in rows:
        per_customer[row["customer_id"]] = per_customer.get(row["customer_id"], 0) + 1
    assert s["revenue_cents"] == sum(r["total_cents"] for r in rows)
    assert s["orders"] == len(rows)
    assert s["repeat_customers"] == sum(1 for n in per_customer.values() if n > 1)
    assert len(s["top_products"]) == 5
    units = [p["units"] for p in s["top_products"]]
    assert units == sorted(units, reverse=True)
    assert s["open_tickets"] == await db.fetchval(
        "SELECT count(*) FROM tickets WHERE store_id = 4 AND status = 'open'")


async def test_unknown_store_returns_404(client):
    assert (await client.get("/dashboard/summary", params={"store_id": 4242})).status_code == 404
