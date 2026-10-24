from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from . import db, pricing, telemetry


class PriceQuote(BaseModel):
    sku: str
    price_cents: int
    base_price_cents: int
    demand_multiplier: float
    low_stock: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await db.create_pool()
    yield
    await app.state.pool.close()


app = FastAPI(title="pricing-service", lifespan=lifespan)
app.add_middleware(telemetry.RequestTimingMiddleware)


@app.get("/health")
async def health(request: Request):
    async with request.app.state.pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


@app.get("/products/{sku}/price", response_model=PriceQuote)
async def product_price(sku: str, request: Request):
    try:
        q = await pricing.quote(request.app.state.pool, sku)
    except pricing.UnknownProduct:
        raise HTTPException(404, f"unknown product {sku}")
    return PriceQuote(sku=q.sku, price_cents=q.price_cents, base_price_cents=q.base_price_cents,
                      demand_multiplier=q.demand_multiplier, low_stock=q.low_stock)


@app.get("/metrics")
async def metrics():
    return telemetry.snapshot()


@app.post("/metrics/reset", status_code=204)
async def reset_metrics():
    telemetry.reset()
