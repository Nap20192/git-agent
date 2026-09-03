"""Подключение к песочнице Экземпляра Агента (создаёт и убивает её hub)."""

from collections.abc import Callable
from typing import Any

from core.ports import Sandbox
from core.runner.ports import SandboxNotProvisionedError
from infra.db.hub_store import HubInstanceStore
from infra.sandbox.opensandbox import connect_sandbox
from pkg.logger import get_logger

log = get_logger(__name__)


async def connect_hub_sandbox(
    ctx: dict[str, Any],
    decrypt: Callable[[bytes | None], str | None],
) -> Sandbox:
    """Подключиться к Экземпляру Сэндбокса, привязанному к Экземпляру Агента.

    Песочницы создаёт и убивает hub по команде юзера; раннер ТОЛЬКО подключается
    по external_id. Нет живого Экземпляра — SandboxNotProvisionedError, Событие
    не обрабатывается. decrypt — расшифровщик *_enc.
    """
    if not ctx.get("sandbox_external_id") or ctx.get("sandbox_status") != "alive":
        raise SandboxNotProvisionedError(
            f"instance {ctx['id']}: sandbox not provisioned (create it in the hub UI)"
        )
    try:
        sandbox = await connect_sandbox(
            ctx["sandbox_external_id"],
            domain=ctx["sandbox_domain"],
            api_key=decrypt(ctx["sandbox_api_key_enc"]),
        )
    except Exception as exc:
        log.warning("hub sandbox connect failed", external_id=ctx["sandbox_external_id"])
        if ctx.get("sandbox_instance_id"):
            await HubInstanceStore().mark_sandbox_dead(ctx["sandbox_instance_id"])
        raise SandboxNotProvisionedError(
            f"instance {ctx['id']}: sandbox is dead (create a new one in the hub UI)"
        ) from exc
    log.info("hub sandbox connected", external_id=ctx["sandbox_external_id"])
    return sandbox
