import asyncio
from dataclasses import dataclass

import asyncpg

from . import telemetry


class UnknownProduct(Exception):
    pass


class InsufficientStock(Exception):
    def __init__(self, available: int):
        super().__init__(f"only {available} left in stock")
        self.available = available


@dataclass
class Reservation:
    id: int
    sku: str
    quantity: int
    unit_price_cents: int
    remaining_stock: int


# A reservation reads the current stock level and writes back the new level.
# Serialize reservations so two requests can never decrement from the same
# snapshot, which would oversell inventory.
_inventory_lock = asyncio.Lock()


async def reserve(pool: asyncpg.Pool, sku: str, quantity: int) -> Reservation:
    with telemetry.span("inventory.lock_wait"):
        await _inventory_lock.acquire()
    try:
        with telemetry.span("inventory.lock_held"):
            return await _reserve_locked(pool, sku, quantity)
    finally:
        _inventory_lock.release()


async def _reserve_locked(pool: asyncpg.Pool, sku: str, quantity: int) -> Reservation:
    with telemetry.span("db.pool_acquire"):
        conn = await pool.acquire()
    try:
        with telemetry.span("db.transaction"):
            async with conn.transaction():
                with telemetry.span("db.select_stock"):
                    product = await conn.fetchrow(
                        "SELECT stock, price_cents FROM products WHERE sku = $1", sku
                    )
                if product is None:
                    raise UnknownProduct(sku)
                if product["stock"] < quantity:
                    raise InsufficientStock(product["stock"])

                remaining = product["stock"] - quantity
                with telemetry.span("db.update_stock"):
                    await conn.execute(
                        "UPDATE products SET stock = $1, updated_at = now() WHERE sku = $2",
                        remaining,
                        sku,
                    )
                with telemetry.span("db.insert_reservation"):
                    reservation_id = await conn.fetchval(
                        "INSERT INTO reservations (sku, quantity, unit_price_cents) "
                        "VALUES ($1, $2, $3) RETURNING id",
                        sku,
                        quantity,
                        product["price_cents"],
                    )
                with telemetry.span("db.insert_inventory_event"):
                    await conn.execute(
                        "INSERT INTO inventory_events (sku, delta, stock_after, reason, reservation_id) "
                        "VALUES ($1, $2, $3, 'reserve', $4)",
                        sku,
                        -quantity,
                        remaining,
                        reservation_id,
                    )
    finally:
        await pool.release(conn)

    return Reservation(
        id=reservation_id,
        sku=sku,
        quantity=quantity,
        unit_price_cents=product["price_cents"],
        remaining_stock=remaining,
    )
