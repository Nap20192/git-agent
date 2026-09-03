"""Исполнение События Экземпляром: лид-граф на чекпоинт-треде + hub-тулзы результатов."""

from __future__ import annotations

import shlex
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.messages import HumanMessage

from core.agents.llm import make_model
from core.ports import Sandbox, SandboxCommandError
from core.runner.events import PR_ACTIONS, Event
from core.runner.history import repair_dangling_tool_calls
from core.runner.ports import InstanceStore
from core.tracing import TurnTracer, inject_langfuse_metadata
from pkg import trace
from pkg.errors import describe
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


PR_BODY_MAX_CHARS = 2000
_FIX_TAIL = (
    "File every confirmed vulnerability with report_finding (file:lines from the diff);"
    " finish with write_report."
)


def _scope_push(event: Event) -> str:
    head = event.commit_sha or "HEAD"
    if event.before_sha:
        return (
            f"SCOPE — changes {event.before_sha}..{head}"
            f"{f' (branch {event.ref})' if event.ref else ''}. Order: 1) git_diff(ref={head!r},"
            f" base={event.before_sha!r}, stat=true) — the list of touched files; 2) commit"
            f" messages: sandbox_run `git log --oneline {event.before_sha}..{head}`; 3) audit"
            " ONLY the touched code: per-file patches git_diff(path=…), context of the changed"
            " lines via read_file/grep_code (callers, sinks, checks). Do not scan the whole"
            " repository; delegate file groups to subagents via task."
        )
    return (
        f"SCOPE — changes of the latest commit {head} (the previous branch state is unknown:"
        f" first push or force-push). Order: 1) git_diff(ref={head!r}, stat=true), then per-file"
        " patches; 2) audit ONLY the touched code, reading context via read_file/grep_code;"
        " do not scan the whole repository. State in the report that the comparison is against"
        " HEAD~1, not the pre-push state."
    )


def _scope_pr(event: Event, merge_base: str | None) -> str:
    head = event.head_sha or event.commit_sha or "HEAD"
    base = merge_base or event.base_sha
    title = f"PR #{event.pr_number}" if event.pr_number else "PR"
    parts = [f"{title}: {event.pr_title}" if event.pr_title else f"{title} with no title."]
    if event.pr_body:
        body = event.pr_body.strip()
        if len(body) > PR_BODY_MAX_CHARS:
            body = body[:PR_BODY_MAX_CHARS] + "… [truncated]"
        parts.append(f"PR description (author intent, context, not ground truth):\n{body}")
    if base:
        diff_call = f"git_diff(ref={head!r}, base={base!r}"
        origin = "merge-base with the base" if merge_base else "PR base"
        scope = f"SCOPE — diff {base}...{head} ({origin}): {diff_call}, stat=true), then"
    else:
        scope = f"SCOPE — changes on the PR head {head}: git_diff(ref={head!r}, stat=true), then"
    parts.append(
        f"{scope} per-file patches git_diff(path=…). REVIEW MODE: findings must sit on diff"
        " lines, with the context of the changed lines read via read_file/grep_code; do not scan"
        " the whole repository, delegate file groups to subagents via task. Separately assess"
        " what the change breaks or widens in the attack surface (new inputs, weakened checks,"
        " new dependencies/permissions). The final write_report is a PR review: verdict, risks,"
        " findings."
    )
    return "\n".join(parts)


def _scope_manual(event: Event) -> str:
    head = event.commit_sha or "HEAD"
    return (
        f"Manual run on commit {head}. If a previous commit has already been reviewed in this"
        f" thread — SCOPE is the changes from it to {head}: git_diff(ref={head!r}, base=<that"
        f" sha>, stat=true); otherwise the latest commit: git_diff(ref={head!r}, stat=true)."
        " Then per-file patches and an audit of ONLY the touched code, reading context via"
        " read_file/grep_code; do not scan the whole repository."
    )


def scope_range(event: Event, merge_base: str | None = None) -> tuple[str, str] | None:
    """(before, after) диапазон изменений События для introducedBy Находок и Отчёта:
    push/manual — before..commit (без before — commit^..commit), PR — merge-base..head,
    full_scan и прочее — None."""
    head = event.head_sha or event.commit_sha
    if not head or event.action == "full_scan":
        return None
    if event.action in PR_ACTIONS:
        base = merge_base or event.base_sha
        return (base, head) if base else (f"{head}^", head)
    if event.action in ("push", "manual"):
        return (event.before_sha or f"{head}^", head)
    return None


def _event_prompt(ctx: dict[str, Any], event: Event, *, merge_base: str | None = None) -> str:
    """Задание хода по типу События: push/PR/manual — аудит КОНКРЕТНЫХ изменений,
    full_scan — полный аудит, прочее с коммитом — разбор в контексте треда."""
    parts = [
        f"Event in repository {ctx['owner']}/{ctx['name']} ({event.provider}): {event.action}."
    ]
    if event.commit_sha:
        parts.append(f"Commit: {event.commit_sha}.")
    if event.ref:
        parts.append(f"Ref: {event.ref}.")
    if event.changed_files:
        parts.append(
            "Changed files (as reported by the provider): " + ", ".join(event.changed_files)
        )
    if ctx.get("prompt"):
        parts.append(str(ctx["prompt"]))
    if event.action == "full_scan":
        parts.append(
            "Run a FULL security audit of the repository at this commit: plan the areas"
            " (entry points, auth, data handling, dependencies, config/secrets), delegate"
            " each area to a subagent via task, collect and file every confirmed finding"
            " with report_finding, and finish with a summary write_report. Do not stop at"
            " the diff — cover the whole codebase."
        )
    elif event.action == "push":
        parts.extend([_scope_push(event), _FIX_TAIL])
    elif event.action in PR_ACTIONS:
        parts.append(_scope_pr(event, merge_base))
    elif event.action == "manual":
        parts.extend([_scope_manual(event), _FIX_TAIL])
    else:
        parts.append(
            "Review this event in the context of what you already know about the repository"
            " (the thread accumulates across events). File confirmed vulnerabilities with"
            " report_finding and record the outcome with write_report at the end."
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
        mcp_tools: list[Any] | None = None,
    ) -> None:
        self._store = store
        self._checkpointer = checkpointer
        self._connect = connect_sandbox
        self._decrypt = decrypt
        self._make_model = make_model
        # коллбэки провайдеров (LangSmith/Langfuse) — из композиционного корня, fail-fast там
        self._tracing_callbacks = list(tracing_callbacks or ())
        # тулы MCP-серверов (CVE-интеллект) — загружены один раз при старте раннера
        self._mcp_tools = list(mcp_tools or ())

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
        self,
        ctx: dict[str, Any],
        sandbox: Sandbox,
        event: Event | None,
        merge_base: str | None = None,
    ) -> tuple[Any, Any]:
        from core.lead import build_lead_profile
        from core.tools.security import build_hub_security_tools

        tools = build_hub_security_tools(
            self._store,
            ctx["id"],
            event.event_id if event else None,
            sandbox=sandbox,
            scope_range=scope_range(event, merge_base) if event else None,
            event_type=event.action if event else "chat",
        )
        model = self._make_model(
            model=ctx["llm_model"],
            api_base=ctx["llm_api_base"],
            api_key=self._decrypt(ctx["llm_api_key_enc"]),
        )
        # ponytail: memory_preset Сборки не резолвится — лид-профиль пресетов пока не берёт
        profile = build_lead_profile(mcp_tools=self._mcp_tools, security_tools=tools)
        graph = profile.build(
            sandbox, model, checkpointer=self._checkpointer, limits=ctx.get("limits") or {}
        )
        return graph, profile

    @asynccontextmanager
    async def _repaired_thread(self, graph: Any, config: dict[str, Any]) -> AsyncIterator[None]:
        """Тред без висящих tool_calls: санация ДО хода (обязательна — иначе
        провайдер отвергнет историю) и best-effort сразу после отмены/краха хода,
        чтобы тред чинился в момент стопа, а не следующего хода (core/runner/history.py)."""
        if self._checkpointer is None:  # без чекпоинтера треда нет (тесты/демо)
            yield
            return
        await repair_dangling_tool_calls(graph, config)
        try:
            yield
        except BaseException:
            try:
                await repair_dangling_tool_calls(graph, config)
            except Exception as exc:  # best-effort: ход уже сорван, чинить будем перед следующим
                log.warning("post-cancel thread repair failed", error=describe(exc))
            raise

    async def _ensure_scope(self, sandbox: Sandbox, event: Event) -> str | None:
        """Коммиты скоупа (before / base / head) должны быть в shallow-клоне до хода;
        для PR — merge-base базы и головы (для двухточечного git_diff = трёхточечному)."""
        from core.repo import ensure_commits

        pair = None
        if event.action in PR_ACTIONS and event.base_sha and (event.head_sha or event.commit_sha):
            pair = (event.base_sha, event.head_sha or event.commit_sha or "")
        shas = [event.before_sha, event.base_sha, event.head_sha, event.commit_sha]
        started = time.monotonic()
        merge_base = await ensure_commits(sandbox, [x for x in shas if x], merge_base_of=pair)
        log.info("scope commits ensured", duration_ms=_ms(started), merge_base=merge_base)
        return merge_base

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
            merge_base = await self._ensure_scope(sandbox, event)
            graph, profile = self._graph(ctx, sandbox, event, merge_base)
            config = self._run_config(ctx, profile, tracer, turn="event")
            async with self._repaired_thread(graph, config):
                async for mode, chunk in graph.astream(
                    {
                        "messages": [
                            HumanMessage(content=_event_prompt(ctx, event, merge_base=merge_base))
                        ]
                    },
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
            graph, profile = self._graph(ctx, sandbox, None)  # чат: без диапазона События
            config = self._run_config(ctx, profile, tracer, turn="chat")
            async with self._repaired_thread(graph, config):
                async for mode, chunk in graph.astream(
                    {"messages": [HumanMessage(content=message)]},
                    config=config,
                    stream_mode=[*profile.stream_modes, "messages"],  # токены ответа в чат
                ):
                    yield mode, serialize(chunk, mode=mode)
        finally:
            log.info("turn summary", **tracer.summary())
            await sandbox.close()
