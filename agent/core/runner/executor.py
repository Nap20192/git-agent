"""Исполнение События Экземпляром: лид-граф на чекпоинт-треде + hub-тулзы результатов."""

from __future__ import annotations

import shlex
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
from core.ports import Sandbox, SandboxCommandError
from core.runner.events import Event
from core.runner.ports import InstanceStore
from pkg.logger import get_logger

log = get_logger(__name__)

_HOSTS = {"github": "github.com", "gitlab": "gitlab.com"}

TERMINAL_MARKER = "__GIT_AGENT_TERM__"
TERMINAL_TIMEOUT_SECONDS = 300.0


def wrap_terminal_command(command: str, cwd: str) -> str:
    """Обернуть команду стрим-консоли: cwd + слитый stderr + маркер (код, $PWD).

    `exec 2>&1` вместо brace-группы: синтаксически битая команда пользователя
    не ломает обёртку целиком — bash печатает ошибку и маркер просто не
    приходит (parse вернёт вывод как есть, cwd не сдвинется).
    """
    return (
        f"exec 2>&1\ncd {shlex.quote(cwd)} 2>/dev/null\n"
        f"{command}\n"
        f'printf "\\n{TERMINAL_MARKER} %d %s" "$?" "$PWD"'
    )


def parse_terminal_output(raw: str) -> tuple[str, int | None, str | None]:
    """Вывод обёрнутой команды → (output, exit_code, new_cwd); без маркера — (raw, None, None)."""
    head, sep, tail = raw.rpartition("\n" + TERMINAL_MARKER + " ")
    if not sep:
        if not raw.startswith(TERMINAL_MARKER + " "):
            return raw, None, None
        head, tail = "", raw[len(TERMINAL_MARKER) + 1 :]
    code_text, _, cwd = tail.partition(" ")
    try:
        code = int(code_text)
    except ValueError:
        return raw, None, None
    return head, code, cwd or None

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
    if event.action == "full_scan":
        parts.append(
            "Проведи ПОЛНЫЙ security-аудит репозитория на этом коммите: составь"
            " план областей (входные точки, auth, работа с данными, зависимости,"
            " конфиги/секреты), делегируй каждую область Сабагенту через task,"
            " собери и зафиксируй все подтверждённые Находки report_finding,"
            " в конце — сводный write_report. Не ограничивайся диффом — весь код."
        )
    else:
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

    async def process_event(
        self,
        ctx: dict[str, Any],
        event: Event,
        on_chunk: Callable[[str, Any], Awaitable[None]] | None = None,
    ) -> None:
        """Исполнить ход; on_chunk получает (mode, serialized chunk) — activity-кадры
        из них сворачивает сервис (core/runner/activity.py)."""
        from core.runtime.serialization import serialize

        sandbox = await self._connect(ctx)
        try:
            from core.repo import advance_repo, prepare_repo, repo_present

            if not await repo_present(sandbox):
                await prepare_repo(sandbox, repo_url(ctx), checkout_ref=event.commit_sha)
            elif event.commit_sha:  # репо уже есть: без переклона, только продвинуть
                await advance_repo(sandbox, event.commit_sha)
            graph, profile = self._graph(ctx, sandbox, event.event_id)
            config = {"configurable": {"thread_id": ctx["thread_id"]}, **profile.run_config}
            async for mode, chunk in graph.astream(
                {"messages": [HumanMessage(content=_event_prompt(ctx, event))]},
                config=config,
                stream_mode=profile.stream_modes,
            ):
                if on_chunk is not None:
                    await on_chunk(mode, serialize(chunk, mode=mode))
        finally:
            await sandbox.close()

    async def terminal(
        self, ctx: dict[str, Any], command: str, cwd: str | None = None
    ) -> tuple[str, int | None, str | None]:
        """Одна команда стрим-консоли в песочнице Экземпляра → (output, exit_code, cwd).

        Connect-only: песочницу создаёт пользователь в UI; нет живой —
        SandboxNotProvisionedError.
        ponytail: каждая команда — свежий shell (порт Sandbox умеет только run);
        между командами переносится cwd (маркером), env/фоновые процессы — нет.
        """
        sandbox = await self._connect(ctx)
        try:
            start = cwd or sandbox.repo_dir
            try:
                raw = await sandbox.run(
                    wrap_terminal_command(command, start),
                    timeout_seconds=TERMINAL_TIMEOUT_SECONDS,
                )
            except SandboxCommandError as exc:
                return exc.stderr or str(exc), exc.exit_code, start
            output, code, new_cwd = parse_terminal_output(raw)
            return output, code, new_cwd or start
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
