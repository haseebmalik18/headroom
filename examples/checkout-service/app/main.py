from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request

from . import db, inventory, orders, telemetry
from .schemas import CheckoutRequest, OrderOut, Product, ReservationOut, ReserveRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await db.create_pool()
    yield
    await app.state.pool.close()


app = FastAPI(title="checkout-service", lifespan=lifespan)
app.add_middleware(telemetry.RequestTimingMiddleware)


@app.get("/health")
async def health(request: Request):
    async with request.app.state.pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


@app.get("/products", response_model=list[Product])
async def list_products(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    async with request.app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT sku, name, price_cents, stock FROM products ORDER BY sku LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
    return [dict(row) for row in rows]


@app.post("/inventory/reserve", response_model=ReservationOut, status_code=201)
async def reserve_inventory(body: ReserveRequest, request: Request):
    try:
        reservation = await inventory.reserve(request.app.state.pool, body.sku, body.quantity)
    except inventory.UnknownProduct:
        raise HTTPException(404, f"unknown sku {body.sku}")
    except inventory.InsufficientStock as exc:
        raise HTTPException(409, str(exc))
    return ReservationOut(
        reservation_id=reservation.id,
        sku=reservation.sku,
        quantity=reservation.quantity,
        unit_price_cents=reservation.unit_price_cents,
        remaining_stock=reservation.remaining_stock,
    )


@app.post("/checkout", response_model=OrderOut, status_code=201)
async def checkout(body: CheckoutRequest, request: Request):
    try:
        order = await orders.checkout(request.app.state.pool, body.reservation_id)
    except orders.UnknownReservation:
        raise HTTPException(404, f"unknown reservation {body.reservation_id}")
    except orders.ReservationNotHeld as exc:
        raise HTTPException(409, str(exc))
    return OrderOut(order_id=order.id, reservation_id=order.reservation_id, total_cents=order.total_cents)


@app.get("/metrics")
async def metrics():
    return telemetry.snapshot()


@app.post("/metrics/reset", status_code=204)
async def reset_metrics():
    telemetry.reset()
