TEST_CATEGORY = 9001  # matches conftest.TEST_CATEGORY


async def test_health(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_listing_is_complete_and_exact(client, test_category):
    response = await client.get(f"/catalog/categories/{test_category}/products")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 900102, "name": "Anchor", "price_cents": 999, "rating_avg": None, "review_count": 0,
         "stock": 3, "in_stock": True},
        {"id": 900101, "name": "Banana stand", "price_cents": 1500, "rating_avg": 4.0, "review_count": 3,
         "stock": 12, "in_stock": True},
        {"id": 900103, "name": "Cactus", "price_cents": 2500, "rating_avg": 1.5, "review_count": 2,
         "stock": 0, "in_stock": False},
        {"id": 900104, "name": "Drum", "price_cents": 4200, "rating_avg": 4.75, "review_count": 4,
         "stock": 7, "in_stock": True},
    ]


async def test_products_without_reviews_are_listed(client, test_category):
    listing = (await client.get(f"/catalog/categories/{test_category}/products")).json()

    anchor = next(p for p in listing if p["name"] == "Anchor")
    assert anchor["review_count"] == 0
    assert anchor["rating_avg"] is None


async def test_review_counts_are_not_multiplied(client, test_category):
    listing = (await client.get(f"/catalog/categories/{test_category}/products")).json()

    assert sum(p["review_count"] for p in listing) == 9


async def test_listing_is_sorted_by_name(client, test_category):
    listing = (await client.get(f"/catalog/categories/{test_category}/products")).json()

    names = [p["name"] for p in listing]
    assert names == sorted(names)


async def test_seeded_category_matches_database(client, db):
    listing = (await client.get("/catalog/categories/7/products")).json()

    expected = await db.fetch(
        """
        SELECT p.id, count(r.id) AS review_count, round(avg(r.rating)::numeric, 2) AS rating_avg
        FROM products p LEFT JOIN reviews r ON r.product_id = p.id
        WHERE p.category_id = 7 GROUP BY p.id ORDER BY p.name
        """
    )
    assert [p["id"] for p in listing] == [row["id"] for row in expected]
    assert [p["review_count"] for p in listing] == [row["review_count"] for row in expected]
    assert [p["rating_avg"] for p in listing] == [
        None if row["rating_avg"] is None else float(row["rating_avg"]) for row in expected
    ]


async def test_empty_category_returns_empty_list(client, db, test_category):
    await db.execute("INSERT INTO categories (id, name) VALUES ($1, 'Empty')", TEST_CATEGORY + 1)

    response = await client.get(f"/catalog/categories/{TEST_CATEGORY + 1}/products")

    assert response.status_code == 200
    assert response.json() == []


async def test_unknown_category_returns_404(client):
    assert (await client.get("/catalog/categories/424242/products")).status_code == 404
