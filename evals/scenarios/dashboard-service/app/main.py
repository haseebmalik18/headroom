from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from . import dashboard, db, telemetry


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await db.create_pool()
    yield
    await app.state.pool.close()


app = FastAPI(title="dashboard-service", lifespan=lifespan)
app.add_middleware(telemetry.RequestTimingMiddleware)


@app.get("/health")
async def health(request: Request):
    async with request.app.state.pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


@app.get("/dashboard/summary")
async def summary(store_id: int, request: Request):
    try:
        return await dashboard.summary(request.app.state.pool, store_id)
    except dashboard.UnknownStore:
        raise HTTPException(404, f"unknown store {store_id}")


@app.get("/metrics")
async def metrics():
    return telemetry.snapshot()


@app.post("/metrics/reset", status_code=204)
async def reset_metrics():
    telemetry.reset()
