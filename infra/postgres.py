"""Postgres-адаптер: пул соединений и операции над repositories/runs."""

import asyncio
import atexit
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from core.config import settings

_pool: ConnectionPool | None = None
_apool: AsyncConnectionPool | None = None
_apool_lock = asyncio.Lock()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings.database_url, kwargs={"row_factory": dict_row}, open=True
        )
        atexit.register(_pool.close)
    return _pool


def get_or_create_repository(url: str, name: str | None = None) -> dict[str, Any]:
    with get_pool().connection() as conn:
        return conn.execute(
            "INSERT INTO repositories (url, name) VALUES (%s, %s)"
            " ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING *",
            (url, name),
        ).fetchone()


def create_run(
    repository_id: int,
    commit_sha: str,
    *,
    llm_api_base: str,
    llm_api_key: str,
    llm_model: str,
) -> dict[str, Any]:
    with get_pool().connection() as conn:
        return conn.execute(
            "INSERT INTO runs"
            " (repository_id, commit_sha, llm_api_base, llm_api_key, llm_model)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (repository_id, commit_sha, llm_api_base, llm_api_key, llm_model),
        ).fetchone()


def finish_run(
    run_id: int,
    *,
    status: str,
    report: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE runs SET status = %s, report = %s, error = %s,"
            " finished_at = now() WHERE id = %s",
            (status, Jsonb(report) if report is not None else None, error, run_id),
        )


async def get_async_pool() -> AsyncConnectionPool:
    global _apool
    async with _apool_lock:
        if _apool is None:
            _apool = AsyncConnectionPool(
                settings.database_url, kwargs={"row_factory": dict_row}, open=False
            )
            await _apool.open()
    return _apool


async def aadd_run_event(run_id: int, kind: str, payload: dict[str, Any]) -> None:
    pool = await get_async_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO run_events (run_id, kind, payload) VALUES (%s, %s, %s)",
            (run_id, kind, Jsonb(payload)),
        )


def add_run_event(run_id: int, kind: str, payload: dict[str, Any]) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO run_events (run_id, kind, payload) VALUES (%s, %s, %s)",
            (run_id, kind, Jsonb(payload)),
        )


def get_run_events(run_id: int) -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT * FROM run_events WHERE run_id = %s ORDER BY id", (run_id,)
        ).fetchall()


def get_run(run_id: int) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        return conn.execute("SELECT * FROM runs WHERE id = %s", (run_id,)).fetchone()
