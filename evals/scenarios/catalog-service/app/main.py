from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from . import catalog, db, telemetry


class ProductListing(BaseModel):
    id: int
    name: str
    price_cents: int
    rating_avg: float | None
    review_count: int
    stock: int
    in_stock: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await db.create_pool()
    yield
    await app.state.pool.close()


app = FastAPI(title="catalog-service", lifespan=lifespan)
app.add_middleware(telemetry.RequestTimingMiddleware)


@app.get("/health")
async def health(request: Request):
    async with request.app.state.pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


@app.get("/catalog/categories/{category_id}/products", response_model=list[ProductListing])
async def category_products(category_id: int, request: Request):
    try:
        return await catalog.category_products(request.app.state.pool, category_id)
    except catalog.UnknownCategory:
        raise HTTPException(404, f"unknown category {category_id}")


@app.get("/metrics")
async def metrics():
    return telemetry.snapshot()


@app.post("/metrics/reset", status_code=204)
async def reset_metrics():
    telemetry.reset()
