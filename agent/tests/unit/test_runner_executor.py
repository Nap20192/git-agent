"""Executor раннера герметично: hub-тулзы результатов, промпт События, repo_url."""

from __future__ import annotations

import asyncio
from typing import Any

from core.ports import SandboxCommandError
from core.runner.events import Event
from core.runner.executor import (
    TERMINAL_MARKER,
    EventExecutor,
    _event_prompt,
    parse_terminal_output,
    repo_url,
    wrap_terminal_command,
)
from core.tools.security import build_hub_security_tools


class RecordingStore:
    def __init__(self):
        self.findings: list[tuple[int, dict[str, Any]]] = []
        self.reports: list[tuple[int, int | None, str]] = []
        self.structured: list[dict[str, Any] | None] = []

    async def add_finding(self, instance_id: int, finding: dict[str, Any]) -> None:
        self.findings.append((instance_id, finding))

    async def add_report(
        self,
        instance_id: int,
        *,
        event_id: int | None,
        summary: str,
        structured: dict[str, Any] | None = None,
    ) -> int:
        self.reports.append((instance_id, event_id, summary))
        self.structured.append(structured)
        return len(self.reports)


def _tools(store) -> dict[str, Any]:
    return {t.name: t for t in build_hub_security_tools(store, instance_id=3, event_id=7)}


def test_tool_names():
    assert set(_tools(RecordingStore())) == {"report_finding", "load_skill", "write_report"}


def test_report_finding_persists():
    async def run():
        store = RecordingStore()
        result = await _tools(store)["report_finding"].ainvoke(
            {
                "title": "SQL-инъекция в login",
                "severity": "High",
                "description": "конкатенация запроса",
                "file": "app/db.py",
                "start_line": 10,
                "end_line": 12,
                "cwe": "CWE-89",
                "confidence": "medium",
                "category": "injection",
                "references": ["https://cwe.mitre.org/data/definitions/89.html"],
            }
        )
        assert result == "recorded high finding: SQL-инъекция в login [app/db.py:10]"
        instance_id, finding = store.findings[0]
        assert instance_id == 3
        assert finding["severity"] == "high"
        assert finding["lineStart"] == 10 and finding["lineEnd"] == 12
        assert finding["cwe"] == "CWE-89" and finding["category"] == "injection"
        assert finding["confidence"] == "medium"
        assert finding["references"] == ["https://cwe.mitre.org/data/definitions/89.html"]
        assert finding["blameCommit"] is None  # без песочницы blame не определяется

    asyncio.run(run())


def test_report_finding_validates():
    async def run():
        store = RecordingStore()
        tool = _tools(store)["report_finding"]
        bad_sev = await tool.ainvoke({"title": "x", "severity": "urgent", "file": "a.py"})
        assert bad_sev.startswith("report_finding: bad severity")
        empty = await tool.ainvoke({"title": " ", "severity": "low", "file": "a.py"})
        assert empty == "report_finding: title is required"
        no_file = await tool.ainvoke({"title": "x", "severity": "low", "description": "y"})
        assert no_file.startswith("report_finding: file is required")
        assert store.findings == []

    asyncio.run(run())


def test_write_report_persists():
    async def run():
        store = RecordingStore()
        tool = _tools(store)["write_report"]
        assert (
            await tool.ainvoke({"summary": "  Итог разбора.  "})
            == "report 1 saved (0 findings attached)"
        )
        instance_id, event_id, summary = store.reports[0]
        assert (instance_id, event_id) == (3, 7)
        assert "## Summary\nИтог разбора." in summary and "| severity |" not in summary
        assert store.structured[0]["summary"] == "Итог разбора."
        assert store.structured[0]["findingsBySeverity"]["high"] == 0
        assert (await tool.ainvoke({"summary": "  "})) == "write_report: summary is required"

    asyncio.run(run())


def test_repo_url():
    assert (
        repo_url({"provider": "github", "owner": "a", "name": "b"}) == "https://github.com/a/b.git"
    )
    assert (
        repo_url({"provider": "gitlab", "owner": "a", "name": "b"}) == "https://gitlab.com/a/b.git"
    )


def test_wrap_terminal_command():
    wrapped = wrap_terminal_command("ls -la", "/repo/sub dir")
    assert wrapped.startswith("exec 2>&1\ncd '/repo/sub dir' 2>/dev/null\nls -la\n")
    assert TERMINAL_MARKER in wrapped


def test_parse_terminal_output():
    assert parse_terminal_output(f"a\nb\n{TERMINAL_MARKER} 0 /repo/x") == ("a\nb", 0, "/repo/x")
    # пустой вывод: маркер с ведущей пустой строкой либо в самом начале
    assert parse_terminal_output(f"\n{TERMINAL_MARKER} 2 /repo") == ("", 2, "/repo")
    assert parse_terminal_output(f"{TERMINAL_MARKER} 0 /repo") == ("", 0, "/repo")
    # cwd с пробелом
    assert parse_terminal_output(f"out\n{TERMINAL_MARKER} 1 /a b") == ("out", 1, "/a b")
    # маркер не пришёл (синтаксически битая команда) — вывод как есть
    assert parse_terminal_output("bash: syntax error") == ("bash: syntax error", None, None)
    assert parse_terminal_output(f"x\n{TERMINAL_MARKER} oops /r") == (
        f"x\n{TERMINAL_MARKER} oops /r",
        None,
        None,
    )


class FakeSandbox:
    repo_dir = "/repo"
    id = "sb-1"

    def __init__(self, raw: str | Exception):
        self.raw = raw
        self.commands: list[str] = []
        self.closed = False

    async def run(self, command: str, *, timeout_seconds: float | None = None) -> str:
        self.commands.append(command)
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw

    async def close(self) -> None:
        self.closed = True


def _terminal_executor(sandbox: FakeSandbox) -> EventExecutor:
    async def connect(ctx):
        return sandbox

    return EventExecutor(
        store=RecordingStore(),
        checkpointer=None,
        connect_sandbox=connect,
        decrypt=lambda b: None,
    )


def test_terminal_runs_in_cwd_and_moves_it():
    async def run():
        sandbox = FakeSandbox(f"file.txt\n{TERMINAL_MARKER} 0 /repo/sub")
        executor = _terminal_executor(sandbox)
        output, code, cwd = await executor.terminal({"id": 3}, "cd sub && ls", None)
        assert (output, code, cwd) == ("file.txt", 0, "/repo/sub")
        assert "cd /repo 2>/dev/null" in sandbox.commands[0]  # дефолт — repo_dir песочницы
        assert sandbox.closed
        # следующая команда — из новой cwd
        sandbox2 = FakeSandbox(f"{TERMINAL_MARKER} 0 /repo/sub")
        output, code, cwd = await _terminal_executor(sandbox2).terminal(
            {"id": 3}, "ls", "/repo/sub"
        )
        assert "cd /repo/sub 2>/dev/null" in sandbox2.commands[0]
        assert cwd == "/repo/sub"

    asyncio.run(run())


def test_terminal_sandbox_error_keeps_cwd():
    async def run():
        sandbox = FakeSandbox(SandboxCommandError("x", 124, "timed out"))
        output, code, cwd = await _terminal_executor(sandbox).terminal({"id": 3}, "sleep 999", "/w")
        assert output == "timed out" and code == 124 and cwd == "/w"
        assert sandbox.closed

    asyncio.run(run())


def test_connect_hub_sandbox_is_connect_only(monkeypatch):
    """Терминал НЕ создаёт песочницу: нет живой — ошибка; мёртвая — метится dead."""
    import pytest

    from core.runner.ports import SandboxNotProvisionedError
    from infra.sandbox import sandboxes

    dead: list[int] = []

    class Store:
        async def mark_sandbox_dead(self, sandbox_instance_id):
            dead.append(sandbox_instance_id)

    monkeypatch.setattr(sandboxes, "HubInstanceStore", Store)

    async def run():
        with pytest.raises(SandboxNotProvisionedError, match="not provisioned"):
            await sandboxes.connect_hub_sandbox(
                {"id": 1, "sandbox_external_id": None}, lambda b: None
            )

        async def broken_connect(external_id, *, domain, api_key):
            raise ConnectionError("gone")

        monkeypatch.setattr(sandboxes, "connect_sandbox", broken_connect)
        ctx = {
            "id": 1,
            "sandbox_external_id": "sb-1",
            "sandbox_status": "alive",
            "sandbox_instance_id": 9,
            "sandbox_domain": "x",
            "sandbox_api_key_enc": None,
        }
        with pytest.raises(SandboxNotProvisionedError, match="sandbox is dead"):
            await sandboxes.connect_hub_sandbox(ctx, lambda b: None)
        assert dead == [9]

    asyncio.run(run())


def test_event_prompt_mentions_context():
    event = Event(
        event_id=7,
        instance_id=3,
        thread_id="t",
        repository_id=5,
        provider="github",
        action="push",
        dedup_key="d",
        commit_sha="abc123",
    )
    ctx = {"owner": "a", "name": "b", "prompt": "Смотри только на auth."}
    text = _event_prompt(ctx, event)
    assert "a/b" in text and "push" in text and "abc123" in text
    assert "Смотри только на auth." in text
    assert "report_finding" in text and "write_report" in text


def test_executor_passes_mcp_tools_to_lead_profile(monkeypatch):
    """MCP-тулы (CVE) из композиционного корня доезжают до build_lead_profile."""
    from types import SimpleNamespace

    import core.lead as lead_mod
    from core.runner.executor import EventExecutor as Executor

    seen: dict = {}

    def fake_profile(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(build=lambda *a, **k: "graph")

    monkeypatch.setattr(lead_mod, "build_lead_profile", fake_profile)
    executor = Executor(
        store=RecordingStore(),
        checkpointer=None,
        connect_sandbox=lambda ctx: None,
        decrypt=lambda b: None,
        make_model=lambda **kw: "model",
        mcp_tools=["cve_tool"],
    )
    ctx = {"id": 3, "llm_model": "m", "llm_api_base": "", "llm_api_key_enc": None}
    graph, _profile = executor._graph(ctx, FakeSandbox("x"), None)
    assert graph == "graph" and seen["mcp_tools"] == ["cve_tool"]
    assert [t.name for t in seen["security_tools"]] == [
        "report_finding",
        "load_skill",
        "write_report",
    ]


def test_ensure_commits_fetches_missing_and_resolves_merge_base():
    from core.repo import ensure_commits

    class ScriptedSandbox(FakeSandbox):
        """cat-file: есть только 'have'; merge-base: успех после unshallow."""

        def __init__(self):
            super().__init__("")
            self.unshallowed = False

        async def run(self, command, *, timeout_seconds=None):
            self.commands.append(command)
            if "cat-file -e" in command:
                if "have^{commit}" not in command:
                    raise SandboxCommandError(command, 1, "")
                return ""
            if "merge-base" in command:
                if not self.unshallowed:
                    raise SandboxCommandError(command, 128, "no merge base")
                return "mb0\n"
            if "--unshallow" in command:
                self.unshallowed = True
            return ""

    async def run():
        sb = ScriptedSandbox()
        mb = await ensure_commits(sb, ["have", "miss", "miss"], merge_base_of=("have", "miss"))
        assert mb == "mb0"
        fetches = [c for c in sb.commands if " fetch " in c]
        assert fetches == [
            "git -C /repo fetch --depth 1 origin miss",  # только отсутствующий, без дублей
            "git -C /repo fetch --unshallow origin || git -C /repo fetch origin",
        ]
        # без пары — merge-base не ищется, провал fetch — warning, не исключение
        failing = FakeSandbox(SandboxCommandError("git", 128, "not our ref"))
        assert await ensure_commits(failing, ["zzz"]) is None

    asyncio.run(run())
