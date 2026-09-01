"""Тесты security-режима: skills-загрузчик, Находки, wire, MCP-конфиг."""

from langchain_core.messages import AIMessage

from core.agents.findings import collect_findings, report_finding
from core.skills import available_skills, load_skills, validate_requested_skills


def test_skills_catalog_and_load():
    skills = available_skills()
    assert len(skills) >= 20
    names = {s["name"] for s in skills}
    assert "sql_injection" in names and "authentication_jwt" in names
    body = load_skills(["sql_injection"])
    assert "sql_injection" in body and "---" not in body["sql_injection"][:5]  # frontmatter снят


def test_validate_requested_skills():
    assert validate_requested_skills(["sql_injection"]) is None
    assert validate_requested_skills(["sql-injection"]) is None  # дефис = подчёркивание
    assert "unknown" in validate_requested_skills(["nope"])
    assert "too many" in validate_requested_skills([f"s{i}" for i in range(6)])
    assert validate_requested_skills([]) is not None


def test_report_finding_validation():
    assert "recorded high" in report_finding.func(title="SQLi", severity="high", description="x")
    assert "bad severity" in report_finding.func(title="t", severity="apocalyptic", description="x")
    assert "required" in report_finding.func(title="", severity="high", description="x")


def test_collect_findings_dedup_and_sort():
    def call(**args):
        return AIMessage(
            content="", tool_calls=[{"name": "report_finding", "args": args, "id": "1"}]
        )

    msgs = [
        call(title="XSS", severity="low", description="a"),
        call(title="RCE", severity="critical", description="b", file="app.py", start_line=5),
        call(title="XSS", severity="low", description="a"),  # дубль
        AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "2"}]),  # не finding
    ]
    findings = collect_findings(msgs)
    assert [f["title"] for f in findings] == ["RCE", "XSS"]  # critical → low, дедуп
    assert findings[0]["file"] == "app.py" and findings[0]["startLine"] == 5


def test_wire_report_surfaces_findings():
    from server.wire import report_to_wire

    report = {
        "answer": "review done",
        "summary": "review done",
        "findings": [{"title": "SQLi", "severity": "high", "description": "x"}],
    }
    wire = report_to_wire(report)
    assert wire["findings"][0]["title"] == "SQLi"
    assert wire["summary"] == "review done"


def test_mcp_config_off_by_default(monkeypatch):
    from core.config import settings
    from infra.mcp import _server_configs

    monkeypatch.setattr(settings, "cve_mcp_path", "")
    assert _server_configs() == {}
    monkeypatch.setattr(settings, "cve_mcp_path", "/nonexistent/path/xyz")
    assert _server_configs() == {}  # путь не существует → выкл
