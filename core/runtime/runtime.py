"""Runtime — библиотечный фасад: «ран — это ресурс, а не запрос».

submit() идемпотентен по построению: тот же (repo, commit, model) → тот же ран
(succeeded → его отчёт; активный → conflict/attach; упавший → resume с
чекпоинта под тем же id). HTTP-слой позже мапит ConflictError→409,
subscribe→SSE (StreamEvent.id — это SSE id), StreamGap → refetch events().
"""

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
        create_sandbox: Callable[[str], Awaitable[Sandbox]],
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
        self._create_sandbox = create_sandbox
        self._get_or_create_repository = get_or_create_repository
        self._checkpointer = checkpointer
        self._manager = RunManager(store, lease_seconds=lease_seconds, grace_seconds=grace_seconds)

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
                    create_sandbox=self._create_sandbox,
                    checkpointer=self._checkpointer,
                    sandbox_name=sandbox_name,
                    is_resume=result.disposition is SubmitDisposition.resumed,
                    checkout_ref=checkout_ref,
                )
            )
            task.set_name(f"git-agent-run-{result.run['id']}")
            self._manager.attach(result.run["id"], task)
        return result

    async def subscribe(
        self, run_id: int, *, last_event_id: str | None = None
    ) -> AsyncIterator[StreamItem]:
        # Терминальный ран без живого стрима: не создавать вечно-тихий стрим —
        # durable-история читается через events(), тут сразу END.
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
            # wait, не await: отменённый таск рана не должен отменять ждущего
            await asyncio.wait([record.task])
        return await self._store.get(run_id)

    async def cancel(self, run_id: int) -> CancelOutcome:
        return await self._manager.cancel(run_id)

    async def shutdown(self, *, timeout: float = 10.0) -> None:
        await self._manager.shutdown(timeout=timeout)


__all__ = ["RunStatus", "Runtime", "SubmitDisposition"]
