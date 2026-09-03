"""Runtime — библиотечный фасад: «ран — это ресурс, а не запрос»."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from core.ports import RunStore, Sandbox, StreamBridge
from core.runtime import worker
from core.runtime.bridge import StreamItem
from core.runtime.manager import RunManager
from core.runtime.profile import PIPELINE_PROFILE, GraphProfile
from core.runtime.schemas import CancelOutcome, RunStatus, SubmitDisposition, SubmitResult
from pkg.logger import get_logger

log = get_logger(__name__)


class Runtime:
    def __init__(
        self,
        *,
        store: RunStore,
        bridge: StreamBridge,
        make_model: Callable[..., Any],
        provision_sandbox: Callable[..., Awaitable[tuple[Sandbox, bool]]],
        get_or_create_repository: Callable[[str], Awaitable[dict[str, Any]]],
        profile: GraphProfile | None = None,
        checkpointer: Any = None,
        lease_seconds: int = 30,
        grace_seconds: int = 10,
    ) -> None:
        self._store = store
        self._bridge = bridge
        self._profile = profile or PIPELINE_PROFILE
        self._make_model = make_model
        self._provision_sandbox = provision_sandbox
        self._get_or_create_repository = get_or_create_repository
        self._checkpointer = checkpointer
        self._manager = RunManager(store, lease_seconds=lease_seconds, grace_seconds=grace_seconds)
        self._chat_locks: dict[int, Any] = {}

    async def start(self) -> None:
        await self._manager.start()

    async def submit(
        self,
        *,
        repo_url: str,
        commit_sha: str,
        llm_api_base: str,
        llm_api_key: str,
        llm_model: str,
        sandbox_name: str = "git",
        checkout_ref: str | None = None,
        instructions: str | None = None,
        limits: dict[str, Any] | None = None,
    ) -> SubmitResult:
        import asyncio

        repo = await self._get_or_create_repository(repo_url)
        result = await self._manager.admit(
            repository_id=repo["id"],
            commit_sha=commit_sha,
            llm_api_base=llm_api_base,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
        )
        if result.disposition in (SubmitDisposition.created, SubmitDisposition.resumed):
            if limits is not None:
                await self._store.set_limits(result.run["id"], limits)
                result.run["limits"] = limits
            record = self._manager.get_local(result.run["id"])
            task = asyncio.create_task(
                worker.run_agent(
                    manager=self._manager,
                    store=self._store,
                    bridge=self._bridge,
                    record=record,
                    run_row=result.run,
                    repo_url=repo_url,
                    profile=self._profile,
                    make_model=self._make_model,
                    provision_sandbox=self._provision_sandbox,
                    checkpointer=self._checkpointer,
                    sandbox_name=sandbox_name,
                    is_resume=result.disposition is SubmitDisposition.resumed,
                    checkout_ref=checkout_ref,
                    instructions=instructions,
                )
            )
            task.set_name(f"git-agent-run-{result.run['id']}")
            self._manager.attach(result.run["id"], task)
        return result

    async def subscribe(
        self, run_id: int, *, last_event_id: str | None = None
    ) -> AsyncIterator[StreamItem]:
        from core.runtime.bridge import END_SENTINEL
        from core.runtime.schemas import TERMINAL_STATUSES

        row = await self._store.get(run_id)
        if row is not None and row["status"] in TERMINAL_STATUSES:
            record = self._manager.get_local(run_id)
            if record is None or not record.finalizing:
                yield END_SENTINEL
                return
        async for item in self._bridge.subscribe(run_id, last_event_id=last_event_id):
            yield item

    async def events(self, run_id: int, *, after_id: int | None = None) -> list[dict[str, Any]]:
        return await self._store.list_events_after(run_id, after_id)

    async def get_run(self, run_id: int) -> dict[str, Any] | None:
        return await self._store.get(run_id)

    async def wait(self, run_id: int) -> dict[str, Any] | None:
        """Дождаться завершения локального таска рана (для CLI/тестов)."""
        import asyncio

        record = self._manager.get_local(run_id)
        if record is not None and record.task is not None:
            await asyncio.wait([record.task])
        return await self._store.get(run_id)

    async def chat(self, run_id: int, message: str) -> AsyncIterator[tuple[str, Any]]:
        """Интерактивный ход поверх чекпоинт-треда завершённого агентного Рана."""
        import asyncio

        from langchain_core.messages import AIMessage, HumanMessage

        from core.runtime.serialization import serialize

        row = await self._store.get(run_id)
        if row is None:
            raise ValueError(f"run {run_id} not found")

        lock = self._chat_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            await self._store.add_event(run_id, "chat", {"role": "user", "text": message})
            model = self._make_model(
                model=row["llm_model"],
                api_base=row["llm_api_base"],
                api_key=row["llm_api_key"],
            )
            sandbox, _reused = await self._provision_sandbox(
                run_id, row.get("sandbox_name") or "git", is_resume=True
            )
            answer = ""
            try:
                graph = self._profile.build(
                    sandbox, model, checkpointer=self._checkpointer, limits=row.get("limits") or {}
                )
                config: dict[str, Any] = {
                    "configurable": {"thread_id": str(run_id)},
                    **self._profile.run_config,
                }
                async for mode, chunk in graph.astream(
                    {"messages": [HumanMessage(content=message)]},
                    config=config,
                    stream_mode=self._profile.stream_modes,
                ):
                    yield mode, serialize(chunk, mode=mode)
                state = await graph.aget_state(config)
                for msg in reversed((state.values or {}).get("messages") or []):
                    if isinstance(msg, AIMessage) and not msg.tool_calls:
                        text = msg.text if isinstance(msg.text, str) else str(msg.content)
                        answer = (text or "").strip()
                        break
            finally:
                await sandbox.close()
            await self._store.add_event(run_id, "chat", {"role": "agent", "text": answer})

    async def chat_history(self, run_id: int) -> list[dict[str, Any]]:
        """Сохранённые чат-ходы Рана (роль+текст) по порядку."""
        events = await self._store.list_events_after(run_id, None, limit=1000)
        out = []
        for e in events:
            if e.get("kind") != "chat":
                continue
            data = (e.get("payload") or {}).get("data") or e.get("payload") or {}
            out.append({"role": data.get("role", ""), "text": data.get("text", "")})
        return out

    async def cancel(self, run_id: int) -> CancelOutcome:
        return await self._manager.cancel(run_id)

    async def delete_run(self, run_id: int) -> bool:
        """Удалить терминальный Ран (store решает; активный → RuntimeError)."""
        return await self._store.delete_run(run_id)

    async def shutdown(self, *, timeout: float = 10.0) -> None:
        await self._manager.shutdown(timeout=timeout)


__all__ = ["RunStatus", "Runtime", "SubmitDisposition"]
