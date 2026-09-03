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
        _pool = ConnectionPool(settings.database_url, kwargs={"row_factory": dict_row}, open=True)
        atexit.register(_pool.close)
    return _pool


def close_pool() -> None:
    """Явно закрыть sync-пул (для graceful shutdown; идемпотентно)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


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
            await _apool.open(wait=True, timeout=30)
    return _apool


async def close_async_pool() -> None:
    """Явно закрыть async-пул (для graceful shutdown; идемпотентно)."""
    global _apool
    async with _apool_lock:
        if _apool is not None:
            await _apool.close()
            _apool = None


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


_RUN_WITH_REPO_SQL = """
    SELECT r.*, repo.url AS repo_url, s.name AS sandbox_name
    FROM runs r
    JOIN repositories repo ON repo.id = r.repository_id
    LEFT JOIN sandboxes s ON s.id = r.sandbox_id
"""


def list_runs_with_repo() -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        return conn.execute(f"{_RUN_WITH_REPO_SQL} ORDER BY r.id DESC").fetchall()


def get_run_with_repo(run_id: int) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        return conn.execute(f"{_RUN_WITH_REPO_SQL} WHERE r.id = %s", (run_id,)).fetchone()


def list_sandboxes_with_counts() -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT s.*, count(r.id) AS run_count FROM sandboxes s"
            " LEFT JOIN runs r ON r.sandbox_id = s.id GROUP BY s.id ORDER BY s.id"
        ).fetchall()


def create_sandbox_row(
    name: str, kind: str, image: str | None, workdir: str | None
) -> dict[str, Any]:
    with get_pool().connection() as conn:
        return conn.execute(
            "INSERT INTO sandboxes (name, kind, image, workdir)"
            " VALUES (%s, %s, %s, %s) RETURNING *",
            (name, kind, image, workdir),
        ).fetchone()
