"""Postgres-адаптер: async-пул соединений (hub.* и чекпоинты живут в одной БД)."""

import asyncio

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from core.config import settings

_apool: AsyncConnectionPool | None = None
_apool_lock = asyncio.Lock()


async def get_async_pool() -> AsyncConnectionPool:
    global _apool
    async with _apool_lock:
        if _apool is None:
            _apool = AsyncConnectionPool(
                settings.database_url, kwargs={"row_factory": dict_row}, open=False
            )
            await _apool.open(wait=True, timeout=30)
    return _apool


async def close_async_pool() -> None:
    """Явно закрыть async-пул (для graceful shutdown; идемпотентно)."""
    global _apool
    async with _apool_lock:
        if _apool is not None:
            await _apool.close()
            _apool = None
