"""Находка v2: blame-порcelain, introducedBy, кэш, структурированный Отчёт и его рендер."""

import asyncio

from core.ports import SandboxCommandError
from core.runner.events import parse_event
from core.runner.executor import scope_range
from core.tools.security import build_hub_security_tools
from core.tools.security.blame import BlameResolver, parse_blame_porcelain
from core.tools.security.report import render_report_markdown

PORCELAIN = """\
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 10 10 2
author Alice
author-mail <alice@example.com>
author-time 1717243200
author-tz +0300
committer Alice
committer-mail <alice@example.com>
committer-time 1717243200
committer-tz +0300
summary Add raw SQL query
filename app/db.py
\tquery = "SELECT * FROM users WHERE id=" + uid
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 11 11
\tcursor.execute(query)
bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 12 12 1
author Bob
author-mail <bob@example.com>
author-time 1717329600
author-tz -0500
summary Log result
filename app/db.py
\tlog(query)
"""


def test_parse_porcelain_picks_dominant_commit_and_iso_date():
    blame = parse_blame_porcelain(PORCELAIN)
    assert blame["blameCommit"] == "a" * 40  # 2 строки против 1
    assert blame["blameAuthor"] == "Alice" and blame["blameEmail"] == "alice@example.com"
    assert blame["blameCommitMessage"] == "Add raw SQL query"
    assert blame["blameDate"] == "2024-06-01T15:00:00+03:00"
    assert blame["introducedBy"] is None
    # пусто / только некоммиченные строки — пустой blame, не исключение
    assert parse_blame_porcelain("")["blameCommit"] is None
    assert (
        parse_blame_porcelain("0" * 40 + " 1 1 1\nauthor Not Committed Yet\n\tx")["blameCommit"]
        is None
    )


class GitSandbox:
    """Фейковая песочница: blame отдаёт PORCELAIN, ancestry — по таблице."""

    repo_dir = "/repo"
    id = None

    def __init__(self, ancestors: dict[tuple[str, str], bool]):
        self.ancestors = ancestors
        self.commands: list[str] = []

    async def run(self, command, *, timeout_seconds=None):
        self.commands.append(command)
        if " blame " in command:
            return PORCELAIN
        if "merge-base --is-ancestor" in command:
            commit, ref = command.split()[-2:]
            if self.ancestors.get((commit, ref)):
                return ""
            raise SandboxCommandError(command, 1, "")
        raise AssertionError(command)

    async def close(self):
        pass


def test_introduced_by_in_and_out_of_range_with_cache():
    a = "a" * 40

    async def run():
        # коммит достижим из after, не из before → внесён этим Событием
        sb = GitSandbox({(a, "after"): True, (a, "before"): False})
        resolver = BlameResolver(sb, ("before", "after"))
        blame = await resolver.resolve("app/db.py", 10, 12)
        assert blame["introducedBy"] == "this_event"
        assert sb.commands[0] == "git -C /repo blame -L 10,12 --porcelain -- app/db.py"
        again = await resolver.resolve("app/db.py", 10, 12)
        assert again is blame and len(sb.commands) == 3  # кэш: ни blame, ни ancestry повторно
        # тот же коммит в другом диапазоне строк — blame заново, ancestry из кэша
        await resolver.resolve("app/db.py", 10, 11)
        assert len(sb.commands) == 4
        # достижим и из before → был раньше
        earlier = BlameResolver(
            GitSandbox({(a, "after"): True, (a, "before"): True}), ("before", "after")
        )
        assert (await earlier.resolve("app/db.py", 10))["introducedBy"] == "earlier"
        # без диапазона (full_scan/чат) — не определяется
        none = BlameResolver(GitSandbox({}), None)
        assert (await none.resolve("app/db.py", 10))["introducedBy"] is None
        # blame упал — пустые поля, не исключение
        broken = GitSandbox({})

        async def fail(command, *, timeout_seconds=None):
            raise SandboxCommandError(command, 128, "no such path")

        broken.run = fail
        assert (await BlameResolver(broken, ("b", "a")).resolve("x", 1))["blameCommit"] is None

    asyncio.run(run())


def test_scope_range_by_event_type():
    base = {
        "eventId": 1,
        "instanceId": 3,
        "threadId": "t",
        "repositoryId": 5,
        "provider": "github",
        "dedupKey": "k",
    }
    assert scope_range(
        parse_event({**base, "action": "push", "commitSha": "c", "beforeSha": "b"})
    ) == ("b", "c")
    assert scope_range(parse_event({**base, "action": "push", "commitSha": "c"})) == ("c^", "c")
    pr = parse_event(
        {**base, "action": "pull_request", "commitSha": "h", "headSha": "h", "baseSha": "b"}
    )
    assert scope_range(pr, "mb") == ("mb", "h") and scope_range(pr) == ("b", "h")
    assert scope_range(parse_event({**base, "action": "full_scan", "commitSha": "c"})) is None
    assert scope_range(parse_event({**base, "action": "ping"})) is None


class Store:
    def __init__(self):
        self.findings, self.reports = [], []

    async def add_finding(self, instance_id, finding):
        self.findings.append(finding)

    async def add_report(self, instance_id, *, event_id, summary, structured=None):
        self.reports.append((summary, structured))
        return 1


def test_report_finding_enriches_blame_and_write_report_structured():
    a = "a" * 40

    async def run():
        store = Store()
        sb = GitSandbox({(a, "head"): True, (a, "mb"): False})
        tools = {
            t.name: t
            for t in build_hub_security_tools(
                store, 3, 7, sandbox=sb, scope_range=("mb", "head"), event_type="pull_request"
            )
        }
        result = await tools["report_finding"].ainvoke(
            {
                "title": "SQLi",
                "severity": "high",
                "description": "concat",
                "file": "app/db.py",
                "start_line": 10,
                "end_line": 12,
                "cwe": "CWE-89",
                "confidence": "medium",
                "category": "injection",
            }
        )
        assert "blame: Alice @ 2024-06-01 aaaaaaa — introduced by this event" in result
        f = store.findings[0]
        assert (
            f["blameAuthor"] == "Alice"
            and f["blameCommit"] == a
            and f["introducedBy"] == "this_event"
        )
        # Находка без строк — blame не запрашивается
        await tools["report_finding"].ainvoke(
            {"title": "Weak config", "severity": "low", "file": "cfg.yml"}
        )
        assert store.findings[1]["blameCommit"] is None
        assert sum(" blame " in c for c in sb.commands) == 1

        out = await tools["write_report"].ainvoke(
            {
                "summary": "Один SQLi в новом коде.",
                "method": ["git_diff", "grep_code", "semgrep"],
                "top_risks": ["SQLi в login"],
                "recommendations": ["параметризовать запрос"],
                "limitations": ["без динамики"],
                "scope": {"files_touched": ["app/db.py"], "lines_changed": 12},
            }
        )
        assert out == "report 1 saved (2 findings attached)"
        summary, structured = store.reports[0]
        assert structured["scope"] == {
            "eventType": "pull_request",  # дефолт системы, модель не задала
            "range": {"base": "mb", "head": "head"},
            "filesTouched": ["app/db.py"],
            "linesChanged": 12,
        }
        assert structured["findingsBySeverity"] == {
            "critical": 0,
            "high": 1,
            "medium": 0,
            "low": 1,
            "info": 0,
        }
        assert structured["method"] == ["git_diff", "grep_code", "semgrep"]
        assert [x["title"] for x in structured["findings"]] == ["SQLi", "Weak config"]
        assert summary.startswith("# Security report pull_request mb...head\n")
        assert (
            "| high | SQLi | app/db.py:10-12 | Alice @ 2024-06-01 `aaaaaaa` (this event) | CWE-89 | medium |"
            in summary
        )
        assert "| low | Weak config | cfg.yml | — | — | — |" in summary
        assert (
            "## Top risks\n- SQLi в login" in summary
            and "## Limitations\n- без динамики" in summary
        )
        assert "- files touched: 1 (app/db.py)" in summary and "- lines changed: 12" in summary

    asyncio.run(run())


def test_render_escapes_pipes_and_handles_push_range():
    md = render_report_markdown(
        {
            "summary": "s",
            "scope": {
                "eventType": "push",
                "range": {"before": "b1", "after": "a1"},
                "filesTouched": [],
                "linesChanged": None,
            },
            "method": [],
            "findingsBySeverity": {"critical": 1, "high": 0, "medium": 0, "low": 0, "info": 0},
            "topRisks": [],
            "recommendations": [],
            "limitations": [],
            "findings": [
                {
                    "severity": "critical",
                    "title": "a | b",
                    "file": "x.py",
                    "lineStart": 3,
                    "lineEnd": 3,
                }
            ],
        }
    )
    assert md.startswith("# Security report push b1..a1\n")
    assert "critical: 1 · high: 0" in md and "| critical | a \\| b | x.py:3 | — | — | — |" in md
    assert "## Method" not in md and "## Top risks" not in md
