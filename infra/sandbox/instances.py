"""Учёт Экземпляров Сэндбокса (живых/мёртвых) в БД + ручное убийство."""

from typing import Any

from infra.db.postgres import get_pool
from infra.sandbox.opensandbox import connect_sandbox
from pkg.logger import get_logger

log = get_logger(__name__)


def record_instance(
    external_id: str, kind: str, image: str | None, run_id: int | None
) -> dict[str, Any]:
    with get_pool().connection() as conn:
        return conn.execute(
            "INSERT INTO sandbox_instances (external_id, kind, image, run_id)"
            " VALUES (%s, %s, %s, %s) RETURNING *",
            (external_id, kind, image, run_id),
        ).fetchone()


def alive_instance_for_run(run_id: int) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT * FROM sandbox_instances WHERE run_id = %s AND status = 'alive'"
            " ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()


def list_instances() -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        return conn.execute("SELECT * FROM sandbox_instances ORDER BY id DESC").fetchall()


def get_instance(instance_id: int) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        return conn.execute(
            "SELECT * FROM sandbox_instances WHERE id = %s", (instance_id,)
        ).fetchone()


def mark_dead(external_id: str) -> dict[str, Any] | None:
    """Пометить Экземпляр мёртвым (идемпотентно: killed_at ставится один раз)."""
    with get_pool().connection() as conn:
        return conn.execute(
            "UPDATE sandbox_instances SET status = 'dead',"
            " killed_at = COALESCE(killed_at, now()) WHERE external_id = %s RETURNING *",
            (external_id,),
        ).fetchone()


async def _destroy_remote(external_id: str) -> None:
    """Уничтожить удалённый сэндбокс (best-effort; мёртвый/отсутствующий — ок)."""
    try:
        sandbox = await connect_sandbox(external_id)
        await sandbox.kill()
    except Exception:
        log.warning("remote destroy failed", external_id=external_id)


async def kill_sandbox(instance_id: int) -> dict[str, Any] | None:
    """Ручное убийство Экземпляра по id: destroy удалённого + status=dead."""
    row = get_instance(instance_id)
    if row is None:
        return None
    if row["status"] == "alive":
        await _destroy_remote(row["external_id"])
    return mark_dead(row["external_id"])


def _alive_externals_for_run(run_id: int) -> list[str]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT external_id FROM sandbox_instances WHERE run_id = %s AND status = 'alive'",
            (run_id,),
        ).fetchall()
    return [r["external_id"] for r in rows]


async def kill_run_instances(run_id: int) -> int:
    """Уничтожить удалённые сэндбоксы всех живых Экземпляров Рана (для удаления Рана).

    Только remote-destroy — строки sandbox_instances удаляет транзакция delete_run.
    """
    import asyncio

    externals = await asyncio.to_thread(_alive_externals_for_run, run_id)
    for ext in externals:
        await _destroy_remote(ext)
    return len(externals)
