"""Исполнение События Экземпляром: лид-граф на чекпоинт-треде + hub-тулзы результатов."""

from __future__ import annotations

import shlex
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage

from core.agents.llm import make_model
from core.ports import Sandbox, SandboxCommandError
from core.runner.events import Event
from core.runner.ports import InstanceStore
from core.tracing import TurnTracer, inject_langfuse_metadata
from pkg import trace
from pkg.logger import get_logger

log = get_logger(__name__)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


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
        tracing_callbacks: list[Any] | None = None,
    ) -> None:
        self._store = store
        self._checkpointer = checkpointer
        self._connect = connect_sandbox
        self._decrypt = decrypt
        self._make_model = make_model
        # коллбэки провайдеров (LangSmith/Langfuse) — из композиционного корня, fail-fast там
        self._tracing_callbacks = list(tracing_callbacks or ())

    def _run_config(
        self, ctx: dict[str, Any], profile: Any, tracer: TurnTracer, *, turn: str
    ) -> dict[str, Any]:
        """Конфиг корневого astream: тред Экземпляра, коллбэки (наш трейсер +
        провайдеры), метаданные для UI провайдеров (trace_id хода — metadata и тег
        `trace:<id>`; session остаётся thread Экземпляра). Наследуется всеми
        вложенными вызовами — тулами и Сабагентами."""
        trace_id = trace.current_or_new()
        config: dict[str, Any] = {
            "configurable": {"thread_id": ctx["thread_id"]},
            "callbacks": [tracer, *self._tracing_callbacks],
            "metadata": {
                "instance_id": ctx["id"],
                "turn": turn,
                "model": ctx["llm_model"],
                trace.FIELD: trace_id,
            },
            "tags": [f"instance:{ctx['id']}", f"turn:{turn}", f"trace:{trace_id}"],
            **profile.run_config,
        }
        inject_langfuse_metadata(
            config,
            thread_id=str(ctx["thread_id"]),
            trace_name=f"instance-{ctx['id']}:{turn}",
            model_name=ctx["llm_model"],
            trace_id=trace_id,
        )
        return config

    async def _timed_connect(self, ctx: dict[str, Any]) -> Sandbox:
        started = time.monotonic()
        sandbox = await self._connect(ctx)
        log.info("sandbox connected", duration_ms=_ms(started), sandbox=sandbox.id)
        return sandbox

    def _graph(
        self, ctx: dict[str, Any], sandbox: Sandbox, event_id: int | None
    ) -> tuple[Any, Any]:
        from core.lead import build_lead_profile
        from core.tools.security import build_hub_security_tools

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
        from core.runner.serialization import serialize

        sandbox = await self._timed_connect(ctx)
        tracer = TurnTracer()
        try:
            from core.repo import advance_repo, prepare_repo, repo_present

            started = time.monotonic()
            if not await repo_present(sandbox):
                await prepare_repo(sandbox, repo_url(ctx), checkout_ref=event.commit_sha)
                log.info("repo cloned", duration_ms=_ms(started), commit=event.commit_sha)
            elif event.commit_sha:  # репо уже есть: без переклона, только продвинуть
                await advance_repo(sandbox, event.commit_sha)
                log.info("repo advanced", duration_ms=_ms(started), commit=event.commit_sha)
            graph, profile = self._graph(ctx, sandbox, event.event_id)
            config = self._run_config(ctx, profile, tracer, turn="event")
            async for mode, chunk in graph.astream(
                {"messages": [HumanMessage(content=_event_prompt(ctx, event))]},
                config=config,
                stream_mode=profile.stream_modes,
            ):
                if on_chunk is not None:
                    await on_chunk(mode, serialize(chunk, mode=mode))
        finally:
            log.info("turn summary", **tracer.summary())
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
        from core.runner.serialization import serialize

        sandbox = await self._timed_connect(ctx)
        tracer = TurnTracer()
        try:
            graph, profile = self._graph(ctx, sandbox, None)
            config = self._run_config(ctx, profile, tracer, turn="chat")
            async for mode, chunk in graph.astream(
                {"messages": [HumanMessage(content=message)]},
                config=config,
                stream_mode=profile.stream_modes,
            ):
                yield mode, serialize(chunk, mode=mode)
        finally:
            log.info("turn summary", **tracer.summary())
            await sandbox.close()
