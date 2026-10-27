"""Store dashboard: headline numbers for the last 30 days."""

import asyncpg

from . import telemetry


class UnknownStore(Exception):
    pass


REVENUE = """
SELECT coalesce(sum(total_cents), 0) AS revenue_cents, count(*) AS orders
FROM orders
WHERE store_id = $1 AND status = 'paid' AND created_at >= now() - interval '30 days'
"""

DAILY_REVENUE = """
SELECT date_trunc('day', created_at)::date AS day, sum(total_cents) AS revenue_cents
FROM orders
WHERE store_id = $1 AND status = 'paid' AND created_at >= now() - interval '30 days'
GROUP BY 1 ORDER BY 1
"""

TOP_PRODUCTS = """
SELECT p.id, p.name, sum(oi.quantity) AS units
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.store_id = $1 AND o.status = 'paid' AND o.created_at >= now() - interval '30 days'
GROUP BY p.id, p.name
ORDER BY units DESC, p.id
LIMIT 5
"""

REPEAT_CUSTOMERS = """
SELECT count(*) AS repeat_customers FROM (
    SELECT customer_id FROM orders
    WHERE store_id = $1 AND status = 'paid' AND created_at >= now() - interval '30 days'
    GROUP BY customer_id HAVING count(*) > 1
) AS repeaters
"""

OPEN_TICKETS = "SELECT count(*) AS open_tickets FROM tickets WHERE store_id = $1 AND status = 'open'"


async def _fetch(pool: asyncpg.Pool, name: str, sql: str, store_id: int):
    with telemetry.span(f"db.{name}"):
        return await pool.fetch(sql, store_id)


async def summary(pool: asyncpg.Pool, store_id: int) -> dict:
    if await pool.fetchval("SELECT 1 FROM stores WHERE id = $1", store_id) is None:
        raise UnknownStore(store_id)
    revenue = (await _fetch(pool, "revenue", REVENUE, store_id))[0]
    daily = await _fetch(pool, "daily_revenue", DAILY_REVENUE, store_id)
    top = await _fetch(pool, "top_products", TOP_PRODUCTS, store_id)
    repeat = (await _fetch(pool, "repeat_customers", REPEAT_CUSTOMERS, store_id))[0]
    tickets = (await _fetch(pool, "open_tickets", OPEN_TICKETS, store_id))[0]

    return {
        "store_id": store_id,
        "revenue_cents": revenue["revenue_cents"],
        "orders": revenue["orders"],
        "daily_revenue": [{"day": row["day"].isoformat(), "revenue_cents": row["revenue_cents"]} for row in daily],
        "top_products": [{"id": row["id"], "name": row["name"], "units": row["units"]} for row in top],
        "repeat_customers": repeat["repeat_customers"],
        "open_tickets": tickets["open_tickets"],
    }
