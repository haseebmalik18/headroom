from dataclasses import dataclass

import asyncpg

from . import telemetry


class UnknownReservation(Exception):
    pass


class ReservationNotHeld(Exception):
    def __init__(self, status: str):
        super().__init__(f"reservation is {status}")
        self.status = status


@dataclass
class Order:
    id: int
    reservation_id: int
    total_cents: int


async def checkout(pool: asyncpg.Pool, reservation_id: int) -> Order:
    async with pool.acquire() as conn:
        with telemetry.span("db.checkout_transaction"):
            async with conn.transaction():
                reservation = await conn.fetchrow(
                    "SELECT quantity, unit_price_cents, status FROM reservations "
                    "WHERE id = $1 FOR UPDATE",
                    reservation_id,
                )
                if reservation is None:
                    raise UnknownReservation(reservation_id)
                if reservation["status"] != "held":
                    raise ReservationNotHeld(reservation["status"])

                total = reservation["quantity"] * reservation["unit_price_cents"]
                order_id = await conn.fetchval(
                    "INSERT INTO orders (reservation_id, total_cents) VALUES ($1, $2) RETURNING id",
                    reservation_id,
                    total,
                )
                await conn.execute(
                    "UPDATE reservations SET status = 'confirmed' WHERE id = $1", reservation_id
                )
    return Order(id=order_id, reservation_id=reservation_id, total_cents=total)
