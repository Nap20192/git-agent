"""Создание/переподключение песочницы по имени из таблицы sandboxes."""

import asyncio
from typing import Any

from core.ports import Sandbox
from infra.db.postgres import get_pool
from infra.sandbox.instances import (
    alive_instance_for_run,
    mark_dead,
    record_instance,
)
from infra.sandbox.localsandbox import LocalSandbox
from infra.sandbox.opensandbox import connect_sandbox
from infra.sandbox.opensandbox import create_sandbox as create_opensandbox
from pkg.logger import get_logger

DEFAULT_SANDBOX = "git"

log = get_logger(__name__)


def get_sandbox_spec(name: str) -> dict[str, Any]:
    with get_pool().connection() as conn:
        row = conn.execute("SELECT * FROM sandboxes WHERE name = %s", (name,)).fetchone()
    if row is None:
        with get_pool().connection() as conn:
            known = [r["name"] for r in conn.execute("SELECT name FROM sandboxes ORDER BY name")]
        raise ValueError(f"Unknown sandbox {name!r}. Known: {', '.join(known)}")
    return row


async def create_sandbox_by_name(name: str = DEFAULT_SANDBOX) -> Sandbox:
    spec = get_sandbox_spec(name)
    match spec["kind"]:
        case "opensandbox":
            return await create_opensandbox(spec["image"])
        case "local":
            return LocalSandbox(spec["workdir"])
        case kind:
            raise NotImplementedError(f"sandbox kind {kind!r} is not implemented yet")


async def provision_sandbox(
    run_id: int, name: str = DEFAULT_SANDBOX, *, is_resume: bool = False
) -> tuple[Sandbox, bool]:
    """Дать песочницу для Рана: reconnect к живому Экземпляру либо новый."""
    spec = get_sandbox_spec(name)
    if is_resume and spec["kind"] == "opensandbox":
        inst = await asyncio.to_thread(alive_instance_for_run, run_id)
        if inst is not None:
            try:
                sandbox = await connect_sandbox(inst["external_id"])
                log.info("sandbox reused via reconnect", external_id=inst["external_id"])
                return sandbox, True
            except Exception:
                log.warning(
                    "sandbox reconnect failed, creating fresh",
                    external_id=inst["external_id"],
                )
                await asyncio.to_thread(mark_dead, inst["external_id"])
    sandbox = await create_sandbox_by_name(name)
    if spec["kind"] == "opensandbox" and sandbox.id:
        await asyncio.to_thread(
            record_instance, sandbox.id, spec["kind"], spec.get("image"), run_id
        )
    return sandbox, False
