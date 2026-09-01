"""Создание песочницы по имени из таблицы sandboxes."""

from typing import Any

from core.ports import Sandbox
from infra.localsandbox import LocalSandbox
from infra.opensandbox import create_sandbox as create_opensandbox
from infra.postgres import get_pool

DEFAULT_SANDBOX = "git"


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
