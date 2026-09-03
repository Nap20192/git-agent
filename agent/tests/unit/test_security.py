"""Тесты security-режима: skills-загрузчик, Находки, wire, MCP-конфиг."""

from langchain_core.messages import AIMessage

from core.skills import available_skills, load_skills, validate_requested_skills
from core.tools.security import collect_findings, report_finding


def test_skills_catalog_and_load():
    skills = available_skills()
    assert len(skills) >= 20
    names = {s["name"] for s in skills}
    assert "sql_injection" in names and "authentication_jwt" in names
    body = load_skills(["sql_injection"])
    assert "sql_injection" in body and "---" not in body["sql_injection"][:5]


def test_validate_requested_skills():
    assert validate_requested_skills(["sql_injection"]) is None
    assert validate_requested_skills(["sql-injection"]) is None
    assert "unknown" in validate_requested_skills(["nope"])
    assert "too many" in validate_requested_skills([f"s{i}" for i in range(6)])
    assert validate_requested_skills([]) is not None


def test_report_finding_validation():
    assert "recorded high" in report_finding.func(title="SQLi", severity="high", file="a.py")
    assert "bad severity" in report_finding.func(title="t", severity="apocalyptic", file="a.py")
    assert "required" in report_finding.func(title="", severity="high", file="a.py")
    assert "file is required" in report_finding.func(title="t", severity="high", description="x")
    assert "normalized" in report_finding.func(
        title="t", severity="low", file="a", category="weird"
    )


def test_collect_findings_dedup_and_sort():
    def call(**args):
        return AIMessage(
            content="", tool_calls=[{"name": "report_finding", "args": args, "id": "1"}]
        )

    msgs = [
        call(title="XSS", severity="low", description="a"),
        call(title="RCE", severity="critical", description="b", file="app.py", start_line=5),
        call(title="XSS", severity="low", description="a"),
        AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "2"}]),
    ]
    findings = collect_findings(msgs)
    assert [f["title"] for f in findings] == ["RCE", "XSS"]
    assert findings[0]["file"] == "app.py" and findings[0]["lineStart"] == 5
    assert findings[0]["category"] == "other" and findings[0]["blameAuthor"] is None


def test_mcp_config_off_by_default(monkeypatch):
    from core.config import settings
    from infra.mcp import _server_configs

    monkeypatch.setattr(settings, "cve_mcp_path", "")
    assert _server_configs() == {}
    monkeypatch.setattr(settings, "cve_mcp_path", "/nonexistent/path/xyz")
    assert _server_configs() == {}


def test_collect_findings_from_events_merges_lead_and_subagents():
    from core.tools.security import collect_findings_from_events, summarize_findings

    events = [
        {
            "kind": "updates",
            "payload": {
                "data": {
                    "model": {
                        "messages": [
                            {
                                "type": "ai",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "name": "report_finding",
                                        "args": {
                                            "title": "XSS",
                                            "severity": "medium",
                                            "description": "d",
                                            "file": "a.js",
                                        },
                                    },
                                ],
                            },
                        ]
                    }
                }
            },
        },
        {
            "kind": "custom",
            "payload": {
                "data": {
                    "type": "task_completed",
                    "subagent_type": "general-purpose",
                    "findings": [
                        {
                            "title": "SQLi",
                            "severity": "critical",
                            "description": "d2",
                            "file": "db.py",
                        }
                    ],
                }
            },
        },
    ]
    findings = collect_findings_from_events(events)
    assert [(f["title"], f["agent"]) for f in findings] == [
        ("SQLi", "general-purpose"),
        ("XSS", "lead"),
    ]
    summary = summarize_findings(findings)
    assert summary["severityCounts"]["critical"] == 1 and summary["total"] == 2
    assert summary["agents"] == ["general-purpose", "lead"]


def test_subagent_result_carries_findings():
    from core.subagents.contract import SubagentResult

    r = SubagentResult(task_id="t")
    assert r.findings == []
    r.findings = [{"title": "x", "severity": "high"}]
    assert r.findings[0]["title"] == "x"
