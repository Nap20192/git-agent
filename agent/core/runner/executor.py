"""Исполнение События Экземпляром: лид-граф на чекпоинт-треде + hub-тулзы результатов."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool, tool

from core.agents.findings import (
    build_load_skill_tool,
    finding_from_args,
    report_finding,
    validate_finding,
)
from core.agents.llm import make_model
from core.ports import Sandbox
from core.runner.events import Event
from core.runner.ports import InstanceStore
from pkg.logger import get_logger

log = get_logger(__name__)

_HOSTS = {"github": "github.com", "gitlab": "gitlab.com"}

# подключение к УЖЕ созданной юзером песочнице Экземпляра (по external_id);
# раннер песочницы не создаёт и не убивает — жизненным циклом рулит hub
SandboxConnect = Callable[[dict[str, Any]], Awaitable[Sandbox]]


def repo_url(ctx: dict[str, Any]) -> str:
    host = _HOSTS.get(ctx["provider"], ctx["provider"])
    return f"https://{host}/{ctx['owner']}/{ctx['name']}.git"


def build_hub_security_tools(
    store: InstanceStore, instance_id: int, event_id: int | None
) -> list[BaseTool]:
    """report_finding/write_report, пишущие в hub.findings/hub.reports (тикет 001:
    «результат агент пишет в БД сам, через тулзу»). Схема и описание report_finding —
    канонические из core/agents/findings, здесь только добавляется персист."""

    async def _report_finding(**kwargs: Any) -> str:
        result = report_finding.func(**kwargs)
        if (
            validate_finding(
                kwargs.get("title", ""), kwargs.get("severity", ""), kwargs.get("description", "")
            )
            is None
        ):
            await store.add_finding(instance_id, finding_from_args(kwargs))
        return result

    persisting_report_finding = StructuredTool(
        name=report_finding.name,
        description=report_finding.description,
        args_schema=report_finding.args_schema,
        coroutine=_report_finding,
    )

    @tool("write_report")
    async def write_report(summary: str) -> str:
        """Записать итоговый Отчёт обработки в базу.

        Вызови один раз в конце работы: связное резюме — что разобрано, общий
        риск, приоритеты. Находки к нему уже привязаны через report_finding.

        Args:
            summary: текст Отчёта (markdown допустим).
        """
        if not summary.strip():
            return "write_report: summary is required"
        report_id = await store.add_report(instance_id, event_id=event_id, summary=summary.strip())
        return f"report {report_id} saved"

    return [persisting_report_finding, build_load_skill_tool(), write_report]


def _event_prompt(ctx: dict[str, Any], event: Event) -> str:
    parts = [
        f"Событие в репозитории {ctx['owner']}/{ctx['name']} ({event.provider}): {event.action}."
    ]
    if event.commit_sha:
        parts.append(f"Коммит: {event.commit_sha}.")
    if event.ref:
        parts.append(f"Ref: {event.ref}.")
    if ctx.get("prompt"):
        parts.append(str(ctx["prompt"]))
    parts.append(
        "Разбери это Событие в контексте того, что ты уже знаешь о репозитории"
        " (тред накапливается между Событиями). Подтверждённые уязвимости фиксируй"
        " report_finding, в конце запиши итог write_report."
    )
    return "\n".join(parts)


class EventExecutor:
    """Поднимает агента из Сборки и исполняет ход на треде Экземпляра."""

    def __init__(
        self,
        *,
        store: InstanceStore,
        checkpointer: Any,
        connect_sandbox: SandboxConnect,
        decrypt: Callable[[bytes | None], str | None],
        make_model: Callable[..., Any] = make_model,
    ) -> None:
        self._store = store
        self._checkpointer = checkpointer
        self._connect = connect_sandbox
        self._decrypt = decrypt
        self._make_model = make_model

    def _graph(
        self, ctx: dict[str, Any], sandbox: Sandbox, event_id: int | None
    ) -> tuple[Any, Any]:
        from core.lead import build_lead_profile

        tools = build_hub_security_tools(self._store, ctx["id"], event_id)
        model = self._make_model(
            model=ctx["llm_model"],
            api_base=ctx["llm_api_base"],
            api_key=self._decrypt(ctx["llm_api_key_enc"]),
        )
        # ponytail: memory_preset Сборки не резолвится — лид-профиль пресетов пока не берёт
        profile = build_lead_profile(security_tools=tools)
        graph = profile.build(
            sandbox, model, checkpointer=self._checkpointer, limits=ctx.get("limits") or {}
        )
        return graph, profile

    async def process_event(self, ctx: dict[str, Any], event: Event) -> None:
        sandbox = await self._connect(ctx)
        try:
            from core.repo import advance_repo, prepare_repo, repo_present

            if not await repo_present(sandbox):
                await prepare_repo(sandbox, repo_url(ctx), checkout_ref=event.commit_sha)
            elif event.commit_sha:  # репо уже есть: без переклона, только продвинуть
                await advance_repo(sandbox, event.commit_sha)
            graph, profile = self._graph(ctx, sandbox, event.event_id)
            config = {"configurable": {"thread_id": ctx["thread_id"]}, **profile.run_config}
            await graph.ainvoke(
                {"messages": [HumanMessage(content=_event_prompt(ctx, event))]}, config=config
            )
        finally:
            await sandbox.close()

    async def chat_stream(
        self, ctx: dict[str, Any], message: str
    ) -> AsyncIterator[tuple[str, Any]]:
        """Ход чата в тред Экземпляра; yield (mode, serialized chunk)."""
        from core.runtime.serialization import serialize

        sandbox = await self._connect(ctx)
        try:
            graph, profile = self._graph(ctx, sandbox, None)
            config = {"configurable": {"thread_id": ctx["thread_id"]}, **profile.run_config}
            async for mode, chunk in graph.astream(
                {"messages": [HumanMessage(content=message)]},
                config=config,
                stream_mode=profile.stream_modes,
            ):
                yield mode, serialize(chunk, mode=mode)
        finally:
            await sandbox.close()
