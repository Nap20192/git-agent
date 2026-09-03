"""Исполнение События Экземпляром: лид-граф на чекпоинт-треде + hub-тулзы результатов."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, tool

from core.agents.findings import SEVERITIES, _finding_from_args
from core.agents.llm import make_model
from core.ports import Sandbox
from core.runner.events import Event
from core.runner.ports import InstanceStore
from pkg.logger import get_logger

log = get_logger(__name__)

_HOSTS = {"github": "github.com", "gitlab": "gitlab.com"}

# провижининг песочницы Экземпляра: (ctx) -> (sandbox, reused); собирается в composition root
SandboxProvision = Callable[[dict[str, Any]], Awaitable[tuple[Sandbox, bool]]]


def repo_url(ctx: dict[str, Any]) -> str:
    host = _HOSTS.get(ctx["provider"], ctx["provider"])
    return f"https://{host}/{ctx['owner']}/{ctx['name']}.git"


def build_hub_security_tools(
    store: InstanceStore, instance_id: int, event_id: int | None
) -> list[BaseTool]:
    """report_finding/write_report, пишущие в hub.findings/hub.reports (тикет 001:
    «результат агент пишет в БД сам, через тулзу»). Схема report_finding — как в
    core/agents/findings.py, но с реальной вставкой."""

    @tool("report_finding")
    async def report_finding(
        title: str,
        severity: str,
        description: str,
        file: str = "",
        start_line: int = 0,
        end_line: int = 0,
        cwe: str = "",
        cve: str = "",
        impact: str = "",
        evidence: str = "",
        remediation: str = "",
        confidence: str = "",
    ) -> str:
        """Зафиксировать security-находку по коду репозитория.

        Вызывай по одному разу на подтверждённую уязвимость, опираясь на реально
        прочитанный код (не на догадку). Находка сохраняется в базу немедленно.

        Args:
            title: краткое название (например «SQL-инъекция в user login»).
            severity: одно из critical/high/medium/low/info.
            description: что за уязвимость и почему это уязвимость.
            file: путь к файлу внутри репозитория (если применимо).
            start_line: первая строка уязвимого участка (0 — неизвестно).
            end_line: последняя строка участка (0 — неизвестно).
            cwe: класс уязвимости, например «CWE-89».
            cve: связанный CVE, если есть, например «CVE-2024-1234».
            impact: к чему приводит эксплуатация.
            evidence: цитата уязвимого кода / доказательство.
            remediation: как исправить.
            confidence: уверенность (high/medium/low) с кратким обоснованием.
        """
        sev = severity.lower().strip()
        if sev not in SEVERITIES:
            return f"report_finding: bad severity {severity!r}; use one of {', '.join(SEVERITIES)}"
        if not title.strip() or not description.strip():
            return "report_finding: title and description are required"
        finding = _finding_from_args(dict(locals()))
        await store.add_finding(instance_id, finding)
        where = f" [{file}:{start_line}]" if file else ""
        return f"recorded {sev} finding: {title.strip()}{where}"

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

    from core.agents.findings import build_security_tools

    load_skill = next(t for t in build_security_tools() if t.name == "load_skill")
    return [report_finding, load_skill, write_report]


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
        provision_sandbox: SandboxProvision,
        decrypt: Callable[[bytes | None], str | None],
    ) -> None:
        self._store = store
        self._checkpointer = checkpointer
        self._provision = provision_sandbox
        self._decrypt = decrypt

    def _graph(self, ctx: dict[str, Any], sandbox: Sandbox, event_id: int | None) -> Any:
        from core.lead import build_lead_profile

        tools = build_hub_security_tools(self._store, ctx["id"], event_id)
        model = make_model(
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
        sandbox, reused = await self._provision(ctx)
        try:
            if not reused or event.commit_sha:
                from core.repo import prepare_repo

                await prepare_repo(sandbox, repo_url(ctx), checkout_ref=event.commit_sha)
            graph, profile = self._graph(ctx, sandbox, event.event_id)
            config = {"configurable": {"thread_id": ctx["thread_id"]}, **profile.run_config}
            await graph.ainvoke(
                {"messages": [HumanMessage(content=_event_prompt(ctx, event))]}, config=config
            )
        finally:
            await sandbox.close()

    async def chat_stream(self, ctx: dict[str, Any], message: str):
        """Ход чата в тред Экземпляра; yield (mode, serialized chunk)."""
        from core.runtime.serialization import serialize

        sandbox, _reused = await self._provision(ctx)
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
