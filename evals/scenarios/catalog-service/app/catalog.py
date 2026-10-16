from decimal import ROUND_HALF_UP, Decimal

import asyncpg

from . import telemetry


class UnknownCategory(Exception):
    pass


async def _query(conn: asyncpg.Connection, sql: str, *args):
    with telemetry.span("db.query"):
        return await conn.fetch(sql, *args)


async def _query_row(conn: asyncpg.Connection, sql: str, *args):
    with telemetry.span("db.query"):
        return await conn.fetchrow(sql, *args)


async def category_products(pool: asyncpg.Pool, category_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        category = await _query_row(conn, "SELECT id FROM categories WHERE id = $1", category_id)
        if category is None:
            raise UnknownCategory(category_id)

        products = await _query(
            conn,
            "SELECT id, name, price_cents FROM products WHERE category_id = $1 ORDER BY name",
            category_id,
        )

        listing = []
        for product in products:
            rating = await _query_row(
                conn,
                "SELECT avg(rating) AS rating_avg, count(*) AS review_count FROM reviews WHERE product_id = $1",
                product["id"],
            )
            stock = await _query_row(conn, "SELECT stock FROM inventory WHERE product_id = $1", product["id"])
            listing.append(
                {
                    "id": product["id"],
                    "name": product["name"],
                    "price_cents": product["price_cents"],
                    "rating_avg": _round(rating["rating_avg"]),
                    "review_count": rating["review_count"],
                    "stock": stock["stock"] if stock else 0,
                    "in_stock": bool(stock and stock["stock"] > 0),
                }
            )
        return listing


def _round(value: Decimal | None) -> float | None:
    return None if value is None else float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
