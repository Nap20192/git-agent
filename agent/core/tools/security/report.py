"""Структурированный Отчёт хода: схема аргументов write_report, сборка структуры
(hub.reports.structured) и markdown-рендер в summary — старый UI видит тот же
богатый отчёт текстом.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.tools.security.findings import SEVERITIES


class ReportRange(BaseModel):
    """Диапазон изменений События: push — before/after, PR — base/head."""

    before: str | None = None
    after: str | None = None
    base: str | None = None
    head: str | None = None


class ReportScope(BaseModel):
    event_type: str = Field(
        "", description="push | pull_request | merge_request | manual | full_scan"
    )
    commit: str | None = Field(None, description="коммит События — HEAD разобранного скоупа")
    range: ReportRange | None = None
    files_touched: list[str] = Field(default_factory=list, description="файлы, реально разобранные")
    lines_changed: int | None = Field(None, description="строк в диффе скоупа, если известно")


class WriteReportArgs(BaseModel):
    """Итоговый Отчёт хода. Вызови один раз в конце. Находки к нему уже привязаны через
    report_finding — их таблицу и счётчики по severity добавит система."""

    summary: str = Field(
        description="связное резюме: что разобрано, общий риск, вердикт (markdown допустим)"
    )
    scope: ReportScope | None = Field(None, description="что именно было в скоупе хода")
    method: list[str] = Field(
        default_factory=list,
        description="какие инструменты/анализаторы применялись (grep_code, git_diff, semgrep, browse…)",
    )
    top_risks: list[str] = Field(default_factory=list, description="главные риски, по убыванию")
    recommendations: list[str] = Field(
        default_factory=list, description="что сделать в первую очередь"
    )
    limitations: list[str] = Field(
        default_factory=list, description="что не проверено / open_proof_gap / ограничения статики"
    )


def findings_by_severity(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(SEVERITIES, 0)
    for f in findings:
        counts[f.get("severity") or "info"] = counts.get(f.get("severity") or "info", 0) + 1
    return counts


def build_structured_report(
    args: WriteReportArgs,
    findings: list[dict[str, Any]],
    *,
    default_scope: ReportScope | None = None,
) -> dict[str, Any]:
    """camelCase-структура для hub.reports.structured; scope модели дополняется
    известным системе (тип События, диапазон), счётчики — из реальных Находок."""
    scope = args.scope or ReportScope()
    if default_scope:
        scope = ReportScope(
            event_type=scope.event_type or default_scope.event_type,
            commit=scope.commit or default_scope.commit,
            range=scope.range or default_scope.range,
            files_touched=scope.files_touched or default_scope.files_touched,
            lines_changed=scope.lines_changed
            if scope.lines_changed is not None
            else default_scope.lines_changed,
        )
    return {
        "summary": args.summary.strip(),
        "scope": {
            "eventType": scope.event_type,
            "commit": scope.commit,
            "range": scope.range.model_dump(exclude_none=True) if scope.range else None,
            "filesTouched": list(scope.files_touched),
            "linesChanged": scope.lines_changed,
        },
        "method": list(args.method),
        "findingsBySeverity": findings_by_severity(findings),
        "topRisks": list(args.top_risks),
        "recommendations": list(args.recommendations),
        "limitations": list(args.limitations),
        "findings": findings,
    }


def _location(f: dict[str, Any]) -> str:
    if not f.get("file"):
        return "—"
    start, end = f.get("lineStart"), f.get("lineEnd")
    lines = f"{start}-{end}" if start and end and end != start else (str(start) if start else "")
    return f"{f['file']}:{lines}" if lines else str(f["file"])


def _blame_cell(f: dict[str, Any]) -> str:
    if not f.get("blameAuthor") and not f.get("blameCommit"):
        return "—"
    author = f.get("blameAuthor") or "?"
    date = (f.get("blameDate") or "")[:10]
    tag = {"this_event": " (this event)", "earlier": " (earlier)"}.get(
        f.get("introducedBy") or "", ""
    )
    sha = f" `{f['blameCommit'][:7]}`" if f.get("blameCommit") else ""
    return f"{author} @ {date}{sha}{tag}".strip()


def _md(text: Any) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def _bullets(title: str, items: list[Any]) -> list[str]:
    if not items:
        return []
    return [f"## {title}", *[f"- {_md(i)}" for i in items], ""]


def render_report_markdown(structured: dict[str, Any]) -> str:
    """Markdown для summary: заголовок, скоуп, метод, счётчики, таблица Находок, риски."""
    scope = structured.get("scope") or {}
    rng = scope.get("range") or {}
    range_text = (
        f"{rng['before']}..{rng['after']}"
        if rng.get("before") and rng.get("after")
        else f"{rng['base']}...{rng['head']}"
        if rng.get("base") and rng.get("head")
        else ""
    )
    commit = f"@ {scope['commit'][:7]}" if scope.get("commit") else ""
    head = " ".join(
        x for x in ("# Security report", scope.get("eventType") or "", commit, range_text) if x
    )
    out = [head, "", "## Summary", structured.get("summary") or "", ""]
    scope_lines = []
    if scope.get("filesTouched"):
        scope_lines.append(
            f"- files touched: {len(scope['filesTouched'])} ({', '.join(scope['filesTouched'][:20])}{'…' if len(scope['filesTouched']) > 20 else ''})"
        )
    if scope.get("linesChanged") is not None:
        scope_lines.append(f"- lines changed: {scope['linesChanged']}")
    if scope_lines:
        out += ["## Scope", *scope_lines, ""]
    out += _bullets("Method", structured.get("method") or [])
    counts = structured.get("findingsBySeverity") or {}
    findings = structured.get("findings") or []
    out += [
        "## Findings",
        " · ".join(f"{sev}: {counts.get(sev, 0)}" for sev in SEVERITIES)
        + f" · total: {len(findings)}",
        "",
    ]
    if findings:
        out += [
            "| severity | title | file:lines | blame author @ date | cwe | confidence |",
            "|---|---|---|---|---|---|",
            *[
                f"| {_md(f.get('severity'))} | {_md(f.get('title'))} | {_md(_location(f))}"
                f" | {_md(_blame_cell(f))} | {_md(f.get('cwe') or '—')} | {_md(f.get('confidence') or '—')} |"
                for f in findings
            ],
            "",
        ]
    out += _bullets("Top risks", structured.get("topRisks") or [])
    out += _bullets("Recommendations", structured.get("recommendations") or [])
    out += _bullets("Limitations", structured.get("limitations") or [])
    return "\n".join(out).rstrip() + "\n"
