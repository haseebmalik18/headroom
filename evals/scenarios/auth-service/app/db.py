import os

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://auth:auth@localhost:5432/auth")
POOL_MIN_SIZE = int(os.environ.get("DB_POOL_MIN_SIZE", "5"))
POOL_MAX_SIZE = int(os.environ.get("DB_POOL_MAX_SIZE", "20"))


async def create_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        DATABASE_URL,
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
    )
