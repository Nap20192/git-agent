"""Точка входа Раннера: `uv run uvicorn runner:app --port 8081`.

Composition root: hub-store + backend-клиент + executor + сервис; lifespan
поднимает консьюмер RabbitMQ, heartbeat и idle-цикл, на выходе опускает
Экземпляры (running→down) и гасит ресурсы.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI

from pkg.logger import get_logger

log = get_logger("runner")


@asynccontextmanager
async def _lifespan(app: FastAPI):
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
    executor = EventExecutor(
        store=store,
        checkpointer=checkpointer,
        provision_sandbox=lambda ctx: provision_hub_sandbox(store, ctx, decrypt_key),
        decrypt=decrypt_key,
    )
    service = RunnerService(
        store=store,
        hub=hub,
        executor=executor,
        name=settings.runner_name,
        address=settings.runner_address,
        slots=settings.runner_slots,
        idle_timeout_seconds=settings.runner_idle_timeout_seconds,
    )
    await service.start()
    app.state.service = service
    tasks = [
        asyncio.create_task(
            consume_events(settings.rabbit_url, service.handle_event), name="runner-consumer"
        ),
        asyncio.create_task(service.heartbeat_loop(), name="runner-heartbeat"),
        asyncio.create_task(service.idle_loop(), name="runner-idle"),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await service.shutdown()
        except Exception:
            log.exception("service shutdown failed")
        await hub.aclose()
        try:
            await cp_cm.__aexit__(None, None, None)
        except Exception:
            log.exception("checkpointer close failed")
        await close_async_pool()
        close_pool()
        log.info("runner shutdown complete")


def create_runner_app() -> FastAPI:
    from infra.server.runner_api import api

    app = FastAPI(title="git-agent runner", lifespan=_lifespan)
    app.include_router(api)
    return app


app = create_runner_app()
