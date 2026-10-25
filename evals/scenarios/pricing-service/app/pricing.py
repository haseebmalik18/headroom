"""Dynamic pricing: a product's price follows recent demand and remaining stock.

Base prices are edited directly in the database by the merchandising tools, and order lines are also
written by the warehouse and marketplace services, so this service does not see every change that
affects a price.
"""

from dataclasses import dataclass
import time

import asyncpg

from . import telemetry


class UnknownProduct(Exception):
    pass


@dataclass(frozen=True)
class Quote:
    sku: str
    base_price_cents: int
    demand_multiplier: float
    low_stock: bool
    price_cents: int


# Prices follow live demand, so a quote may be reused only briefly. The product
# team's rule: a change in base price or demand must show within 3 seconds.
CACHE_TTL_S = 2.0
LOW_STOCK = 20

_cache: dict[str, tuple[float, Quote]] = {}


async def quote(pool: asyncpg.Pool, sku: str) -> Quote:
    cached = _cache.get(sku)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_S:
        return cached[1]
    with telemetry.span("pricing.compute"):
        fresh = await _compute(pool, sku)
    _cache[sku] = (time.monotonic(), fresh)
    return fresh


def demand_multiplier(last_hour: int, last_week: int) -> float:
    """How far the last hour runs ahead of (or behind) the weekly hourly average, scaled into 0.90-1.50."""
    hourly_average = last_week / (7 * 24) if last_week else 0
    if not hourly_average:
        return 1.0
    ratio = last_hour / hourly_average
    return round(min(1.5, max(0.9, 1.0 + 0.25 * (ratio - 1.0))), 4)


def price(base_price_cents: int, multiplier: float, low_stock: bool) -> int:
    return round(base_price_cents * multiplier * (1.1 if low_stock else 1.0))


async def _compute(pool: asyncpg.Pool, sku: str) -> Quote:
    with telemetry.span("db.pool_acquire"):
        conn = await pool.acquire()
    try:
        with telemetry.span("db.demand_query"):
            row = await conn.fetchrow(
                """
                SELECT p.base_price_cents, p.stock,
                       COALESCE(SUM(o.quantity) FILTER (WHERE o.ordered_at > now() - interval '1 hour'), 0) AS last_hour,
                       COALESCE(SUM(o.quantity), 0) AS last_week
                FROM products p
                LEFT JOIN order_lines o ON o.sku = p.sku AND o.ordered_at > now() - interval '7 days'
                WHERE p.sku = $1
                GROUP BY p.sku, p.base_price_cents, p.stock
                """,
                sku,
            )
    finally:
        await pool.release(conn)
    if row is None:
        raise UnknownProduct(sku)
    multiplier = demand_multiplier(row["last_hour"], row["last_week"])
    low_stock = row["stock"] < LOW_STOCK
    return Quote(sku=sku, base_price_cents=row["base_price_cents"], demand_multiplier=multiplier,
                 low_stock=low_stock, price_cents=price(row["base_price_cents"], multiplier, low_stock))
