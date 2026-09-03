"""Композиционный корень: сборка Раннера и его graceful-разбор."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from pkg.logger import get_logger

log = get_logger("deps")


@dataclass
class RunnerDeps:
    """Готовый к работе Раннер: сервис + фоновые циклы уже запущены."""

    service: Any


async def _supervised(name: str, factory: Any) -> None:
    """Фоновый цикл живёт, пока жив раннер: упал — лог с трейсбеком и рестарт с backoff.

    Без этого падение консьюмера (Rabbit недоступен на старте) оставляло раннер
    работать молча, без Событий.
    """
    from pkg.errors import describe

    delay = 1.0
    while True:
        try:
            await factory()
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception(
                "background loop crashed, restarting",
                loop=name,
                error=describe(exc),
                retry_in_s=delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)


@asynccontextmanager
async def runner_deps():
    """Собрать Раннера (консьюмер Событий), при выходе — graceful shutdown.

    Порядок гашения: фоновые циклы → Экземпляры (running→down) → HTTP-клиент →
    чекпоинтер → async-пул БД. Песочницы не трогаем (no-TTL).
    """
    from functools import partial

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from core.config import settings
    from core.runner.crypto import decrypt
    from core.runner.executor import EventExecutor
    from core.runner.service import RunnerService
    from core.tracing import build_tracing_callbacks
    from infra.db.hub_store import HubInstanceStore
    from infra.db.postgres import close_async_pool
    from infra.hub_client import HttpHubClient
    from infra.mcp import load_mcp_tools
    from infra.rabbit import consume_events
    from infra.sandbox.sandboxes import connect_hub_sandbox
    from pkg.errors import describe

    store = HubInstanceStore()
    hub = HttpHubClient(hub_url=settings.hub_url, token=settings.runner_token)
    decrypt_key = partial(decrypt, key_hex=settings.secrets_key)
    cp_cm = AsyncPostgresSaver.from_conn_string(settings.database_url)
    checkpointer = await cp_cm.__aenter__()
    service = RunnerService(
        store=store,
        hub=hub,
        executor=EventExecutor(
            store=store,
            checkpointer=checkpointer,
            connect_sandbox=lambda ctx: connect_hub_sandbox(ctx, decrypt_key),
            decrypt=decrypt_key,
            tracing_callbacks=build_tracing_callbacks(),  # fail-fast: включён, но не настроен
            mcp_tools=await load_mcp_tools(),  # CVE MCP; недоступен ⇒ warn + без него
        ),
        name=settings.runner_name,
        address=settings.runner_address,
        slots=settings.runner_slots,
        idle_timeout_seconds=settings.runner_idle_timeout_seconds,
    )
    tasks: list[asyncio.Task] = []
    try:
        await service.start()
        tasks = [
            asyncio.create_task(_supervised(name, factory), name=name)
            for name, factory in (
                ("consumer", lambda: consume_events(settings.rabbitmq_url, service.handle_event)),
                ("heartbeat", service.heartbeat_loop),
                ("idle", service.idle_loop),
            )
        ]
        log.info("runner deps ready", name=service.name, slots=service.slots)
        yield RunnerDeps(service=service)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for step, closer in (
            ("service shutdown", service.shutdown),
            ("hub client close", hub.aclose),
            ("checkpointer close", lambda: cp_cm.__aexit__(None, None, None)),
            ("async pool close", close_async_pool),
        ):
            try:
                await closer()
            except Exception as exc:
                log.exception("shutdown step failed, continuing", step=step, error=describe(exc))
        log.info("runner shutdown complete")
