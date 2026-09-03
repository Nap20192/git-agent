"""Композиционный корень приложения."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from pkg.logger import get_logger

log = get_logger("deps")


@dataclass
class AppDeps:
    """Готовые к работе зависимости приложения."""

    runtimes: dict[str, Any]
    checkpointer: Any


def _build_runtimes(*, checkpointer: Any, mcp_tools: list) -> dict[str, Any]:
    """Рантаймы pipeline и agent над общими store/bridge/checkpointer."""
    from core.agents.llm import make_model
    from core.lead import build_lead_profile
    from core.runtime import MemoryStreamBridge, Runtime
    from core.runtime.profile import PIPELINE_PROFILE
    from infra.db.postgres import get_or_create_repository
    from infra.db.run_store import PostgresRunStore
    from infra.sandbox.sandboxes import provision_sandbox

    async def repository(url: str) -> dict[str, Any]:
        return await asyncio.to_thread(get_or_create_repository, url)

    store, bridge = PostgresRunStore(), MemoryStreamBridge()

    def make_runtime(profile: Any) -> Runtime:
        return Runtime(
            store=store,
            bridge=bridge,
            make_model=make_model,
            provision_sandbox=provision_sandbox,
            get_or_create_repository=repository,
            profile=profile,
            checkpointer=checkpointer,
        )

    return {
        "pipeline": make_runtime(PIPELINE_PROFILE),
        "agent": make_runtime(build_lead_profile(mcp_tools)),
    }


@dataclass
class RunnerDeps:
    """Готовый к работе Раннер: сервис + фоновые циклы уже запущены."""

    service: Any


@asynccontextmanager
async def runner_deps():
    """Собрать Раннера (консьюмер Событий), при выходе — graceful shutdown.

    Порядок гашения: фоновые циклы → Экземпляры (running→down) → HTTP-клиент →
    чекпоинтер → пулы БД. Песочницы не трогаем (no-TTL).
    """
    from functools import partial

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from core.config import settings
    from core.runner.crypto import decrypt
    from core.runner.executor import EventExecutor
    from core.runner.service import RunnerService
    from infra.db.hub_store import HubInstanceStore
    from infra.db.postgres import close_async_pool, close_pool
    from infra.hub_client import HttpHubClient
    from infra.rabbit import consume_events
    from infra.sandbox.sandboxes import provision_hub_sandbox

    store = HubInstanceStore()
    hub = HttpHubClient(backend_url=settings.backend_url, token=settings.runner_token)
    decrypt_key = partial(decrypt, key_b64=settings.hub_enc_key)
    cp_cm = AsyncPostgresSaver.from_conn_string(settings.database_url)
    checkpointer = await cp_cm.__aenter__()
    service = RunnerService(
        store=store,
        hub=hub,
        executor=EventExecutor(
            store=store,
            checkpointer=checkpointer,
            provision_sandbox=lambda ctx: provision_hub_sandbox(store, ctx, decrypt_key),
            decrypt=decrypt_key,
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
            asyncio.create_task(
                consume_events(settings.rabbit_url, service.handle_event), name="runner-consumer"
            ),
            asyncio.create_task(service.heartbeat_loop(), name="runner-heartbeat"),
            asyncio.create_task(service.idle_loop(), name="runner-idle"),
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
            except Exception:
                log.exception(f"runner {step} failed")
        close_pool()
        log.info("runner shutdown complete")


@asynccontextmanager
async def app_deps():
    """Собрать зависимости, отдать AppDeps, при выходе — graceful shutdown."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from core.config import settings
    from infra.db.postgres import close_async_pool, close_pool
    from infra.mcp import load_mcp_tools

    runtimes: dict[str, Any] = {}
    cp_cm = AsyncPostgresSaver.from_conn_string(settings.database_url)
    checkpointer = await cp_cm.__aenter__()
    try:
        mcp_tools = await load_mcp_tools()
        runtimes = _build_runtimes(checkpointer=checkpointer, mcp_tools=mcp_tools)
        for rt in runtimes.values():
            await rt.start()
        log.info("app deps ready", runtimes=list(runtimes))
        yield AppDeps(runtimes=runtimes, checkpointer=checkpointer)
    finally:
        await _graceful_shutdown(runtimes, cp_cm, close_async_pool, close_pool)


async def _graceful_shutdown(
    runtimes: dict[str, Any], cp_cm: Any, close_async_pool: Any, close_pool: Any
) -> None:
    """Погасить в порядке зависимостей; каждый шаг изолирован — сбой не рвёт остальные."""
    log.info("graceful shutdown: draining agents/runtimes")
    for rt in runtimes.values():
        try:
            await rt.shutdown()
        except Exception:
            log.exception("runtime shutdown failed")
    log.info("graceful shutdown: closing checkpointer")
    try:
        await cp_cm.__aexit__(None, None, None)
    except Exception:
        log.exception("checkpointer close failed")
    log.info("graceful shutdown: closing db pools")
    try:
        await close_async_pool()
    except Exception:
        log.exception("async pool close failed")
    try:
        close_pool()
    except Exception:
        log.exception("sync pool close failed")
    log.info("graceful shutdown complete")
