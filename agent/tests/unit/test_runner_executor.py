"""Executor раннера герметично: hub-тулзы результатов, промпт События, repo_url."""

from __future__ import annotations

import asyncio
from typing import Any

from core.runner.events import Event
from core.runner.executor import _event_prompt, build_hub_security_tools, repo_url


class RecordingStore:
    def __init__(self):
        self.findings: list[tuple[int, dict[str, Any]]] = []
        self.reports: list[tuple[int, int | None, str]] = []

    async def add_finding(self, instance_id: int, finding: dict[str, Any]) -> None:
        self.findings.append((instance_id, finding))

    async def add_report(self, instance_id: int, *, event_id: int | None, summary: str) -> int:
        self.reports.append((instance_id, event_id, summary))
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
            }
        )
        assert result == "recorded high finding: SQL-инъекция в login [app/db.py:10]"
        instance_id, finding = store.findings[0]
        assert instance_id == 3
        assert finding["severity"] == "high"
        assert finding["startLine"] == 10 and finding["endLine"] == 12
        assert finding["cwe"] == "CWE-89"
        assert finding["confidence"] == "medium"

    asyncio.run(run())


def test_report_finding_validates():
    async def run():
        store = RecordingStore()
        tool = _tools(store)["report_finding"]
        bad_sev = await tool.ainvoke({"title": "x", "severity": "urgent", "description": "y"})
        assert bad_sev.startswith("report_finding: bad severity")
        empty = await tool.ainvoke({"title": " ", "severity": "low", "description": "y"})
        assert empty == "report_finding: title and description are required"
        assert store.findings == []

    asyncio.run(run())


def test_write_report_persists():
    async def run():
        store = RecordingStore()
        tool = _tools(store)["write_report"]
        assert await tool.ainvoke({"summary": "  Итог разбора.  "}) == "report 1 saved"
        assert store.reports == [(3, 7, "Итог разбора.")]
        assert (await tool.ainvoke({"summary": "  "})) == "write_report: summary is required"

    asyncio.run(run())


def test_repo_url():
    assert repo_url({"provider": "github", "owner": "a", "name": "b"}) == "https://github.com/a/b.git"
    assert repo_url({"provider": "gitlab", "owner": "a", "name": "b"}) == "https://gitlab.com/a/b.git"


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
