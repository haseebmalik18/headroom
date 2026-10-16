import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, db, telemetry


class Credentials(BaseModel):
    username: str
    password: str


class Registration(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8)
    display_name: str


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await db.create_pool()
    monitor = asyncio.create_task(telemetry.monitor_event_loop())
    yield
    monitor.cancel()
    await app.state.pool.close()


app = FastAPI(title="auth-service", lifespan=lifespan)
app.add_middleware(telemetry.RequestTimingMiddleware)


async def current_user(request: Request, authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    async with request.app.state.pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT u.id, u.username, u.display_name, u.password_hash FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token = $1",
            authorization.removeprefix("Bearer "),
        )
    if user is None:
        raise HTTPException(401, "invalid token")
    return dict(user)


@app.get("/health")
async def health(request: Request):
    async with request.app.state.pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


@app.post("/register", status_code=201)
async def register(body: Registration, request: Request):
    password_hash = auth.hash_password(body.password)
    async with request.app.state.pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (username, password_hash, display_name) VALUES ($1, $2, $3) "
            "ON CONFLICT (username) DO NOTHING RETURNING id",
            body.username, password_hash, body.display_name,
        )
    if user_id is None:
        raise HTTPException(409, "username taken")
    return {"id": user_id}


@app.post("/login")
async def login(body: Credentials, request: Request):
    async with request.app.state.pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id, password_hash FROM users WHERE username = $1", body.username)
    if user is None or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "invalid credentials")
    token = auth.new_token()
    async with request.app.state.pool.acquire() as conn:
        await conn.execute("INSERT INTO sessions (token, user_id) VALUES ($1, $2)", token, user["id"])
    return {"token": token}


@app.get("/me")
async def me(request: Request, authorization: str | None = Header(default=None)):
    user = await current_user(request, authorization)
    return {"id": user["id"], "username": user["username"], "display_name": user["display_name"]}


@app.post("/password", status_code=204)
async def change_password(body: PasswordChange, request: Request,
                          authorization: str | None = Header(default=None)):
    user = await current_user(request, authorization)
    if not auth.verify_password(body.old_password, user["password_hash"]):
        raise HTTPException(401, "invalid credentials")
    new_hash = auth.hash_password(body.new_password)
    async with request.app.state.pool.acquire() as conn:
        await conn.execute("UPDATE users SET password_hash = $1 WHERE id = $2", new_hash, user["id"])


@app.get("/metrics")
async def metrics():
    return telemetry.snapshot()


@app.post("/metrics/reset", status_code=204)
async def reset_metrics():
    telemetry.reset()
