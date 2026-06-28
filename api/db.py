"""
Пул соединений с Postgres для API.

Создаётся один раз на старте приложения (FastAPI lifespan) и переиспользуется
всеми запросами — в отличие от rag/chain.py, где каждый вызов открывает и
закрывает отдельное соединение.
"""

import os
from typing import Optional

import asyncpg

POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://user:password@localhost:5432/mydb")

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=1, max_size=10)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Пул соединений не инициализирован (init_pool не вызван)")
    return _pool
