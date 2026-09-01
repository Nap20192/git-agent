"""CRUD сохранённых LLM-подключений (таблица connections) + проверка endpoint."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from infra.postgres import get_pool


def list_connections() -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        return list(conn.execute("SELECT * FROM connections ORDER BY id"))


def get_connection(connection_id: int) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT * FROM connections WHERE id = %s", (connection_id,)
        ).fetchone()


def create_connection(name: str, api_base: str, api_key: str, model: str) -> dict[str, Any]:
    with get_pool().connection() as conn:
        return conn.execute(
            "INSERT INTO connections (name, api_base, api_key, model)"
            " VALUES (%s, %s, %s, %s) RETURNING *",
            (name, api_base, api_key, model),
        ).fetchone()


def delete_connection(connection_id: int) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM connections WHERE id = %s", (connection_id,))


async def check_connection(connection_id: int) -> dict[str, Any] | None:
    """GET {api_base}/models с ключом; результат — в last_check."""
    row = get_connection(connection_id)
    if row is None:
        return None
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{row['api_base'].rstrip('/')}/models",
                headers={"Authorization": f"Bearer {row['api_key']}"},
            )
        ok = resp.status_code < 400
    except Exception:
        ok = False
    last_check = {
        "ok": ok,
        "latencyMs": int((time.monotonic() - started) * 1000),
        "at": datetime.now(UTC).isoformat(),
    }
    with get_pool().connection() as conn:
        return conn.execute(
            "UPDATE connections SET last_check = %s WHERE id = %s RETURNING *",
            (json.dumps(last_check), connection_id),
        ).fetchone()
