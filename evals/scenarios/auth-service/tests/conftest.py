import os
import uuid

import asyncpg
import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://auth:auth@localhost:5432/auth")


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as c:
        yield c


@pytest.fixture
async def db():
    conn = await asyncpg.connect(DATABASE_URL)
    yield conn
    await conn.close()


@pytest.fixture
async def new_user(client, db):
    """Registers a throwaway user; removed afterwards."""
    username = f"test-{uuid.uuid4().hex[:10]}"
    password = "correct horse battery"
    response = await client.post("/register", json={"username": username, "password": password,
                                                     "display_name": "Test User"})
    assert response.status_code == 201
    yield username, password
    await db.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username = $1)", username)
    await db.execute("DELETE FROM users WHERE username = $1", username)
