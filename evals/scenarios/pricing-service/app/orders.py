from dataclasses import dataclass

import asyncpg

from . import telemetry


class UnknownProduct(Exception):
    pass


class OutOfStock(Exception):
    def __init__(self, available: int):
        super().__init__(f"only {available} left")
        self.available = available


@dataclass(frozen=True)
class Order:
    id: int
    sku: str
    quantity: int
    remaining_stock: int


async def place(pool: asyncpg.Pool, sku: str, quantity: int) -> Order:
    """Take stock and record the order line in one transaction; never sells more than is in stock."""
    with telemetry.span("db.pool_acquire"):
        conn = await pool.acquire()
    try:
        async with conn.transaction():
            with telemetry.span("db.take_stock"):
                remaining = await conn.fetchval(
                    "UPDATE products SET stock = stock - $2 WHERE sku = $1 AND stock >= $2 RETURNING stock",
                    sku, quantity,
                )
            if remaining is None:
                available = await conn.fetchval("SELECT stock FROM products WHERE sku = $1", sku)
                if available is None:
                    raise UnknownProduct(sku)
                raise OutOfStock(available)
            with telemetry.span("db.insert_order_line"):
                order_id = await conn.fetchval(
                    "INSERT INTO order_lines (sku, quantity, ordered_at) VALUES ($1, $2, now()) RETURNING id",
                    sku, quantity,
                )
    finally:
        await pool.release(conn)
    return Order(id=order_id, sku=sku, quantity=quantity, remaining_stock=remaining)
