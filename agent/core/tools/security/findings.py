"""Модель security-Находки: валидация, нормализация, сбор из истории/событий.

Модель — по образцу strix, адаптирована под статический анализ кода
(файл/строки вместо endpoint/method). Находки НЕ хранятся в коллекторе:
тул report_finding только валидирует и подтверждает, а извлекаются они из
tool_calls в истории сообщений хода.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

SEVERITIES = ("critical", "high", "medium", "low", "info")
CATEGORIES = (
    "injection",
    "auth",
    "crypto",
    "secrets",
    "deps",
    "config",
    "xss",
    "ssrf",
    "path",
    "logic",
    "other",
)
CONFIDENCES = ("high", "medium", "low")
FINDING_TOOL = "report_finding"
# blame заполняет раннер (core/tools/security/blame.py), модель эти поля не передаёт
BLAME_FIELDS = (
    "blameAuthor",
    "blameEmail",
    "blameCommit",
    "blameDate",
    "blameCommitMessage",
    "introducedBy",
)


def validate_finding(title: str, severity: str, file: str = "") -> str | None:
    """Ошибка валидации Находки или None; общая для всех вариантов report_finding.
    Обязательны title, severity и file (контракт Находки v2)."""
    if severity.lower().strip() not in SEVERITIES:
        return f"report_finding: bad severity {severity!r}; use one of {', '.join(SEVERITIES)}"
    if not title.strip():
        return "report_finding: title is required"
    if not str(file or "").strip():
        return (
            "report_finding: file is required (path inside the repository; for repo-wide"
            " issues name the closest manifest/config file)"
        )
    return None


def normalize_category(value: Any) -> str:
    cat = str(value or "").lower().strip()
    return cat if cat in CATEGORIES else "other"


def _confidence(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    head = text.split()[0].lower().strip(":;,.")
    return head if head in CONFIDENCES else text


def finding_from_args(args: dict[str, Any]) -> dict[str, Any]:
    """Нормализация аргументов report_finding в camelCase-Находку."""
    sev = str(args.get("severity", "")).lower().strip()
    refs = args.get("references") or []
    if isinstance(refs, str):
        refs = [refs]
    finding: dict[str, Any] = {
        "title": str(args.get("title", "")).strip(),
        "severity": sev if sev in SEVERITIES else "info",
        "description": str(args.get("description", "")).strip(),
        "impact": str(args.get("impact", "")).strip() or None,
        "confidence": _confidence(args.get("confidence")),
        "category": normalize_category(args.get("category")),
        "file": str(args.get("file", "")).strip() or None,
        "lineStart": int(args.get("start_line") or args.get("lineStart") or 0) or None,
        "lineEnd": int(args.get("end_line") or args.get("lineEnd") or 0) or None,
        "cwe": str(args.get("cwe", "")).strip() or None,
        "cve": str(args.get("cve", "")).strip() or None,
        "evidence": str(args.get("evidence", "")).strip() or None,
        "remediation": str(args.get("remediation", "")).strip() or None,
        "references": [str(r).strip() for r in refs if str(r).strip()],
    }
    finding.update(dict.fromkeys(BLAME_FIELDS))
    return finding


_SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}


def collect_findings(messages: list[Any]) -> list[dict[str, Any]]:
    """Собрать Находки из вызовов report_finding в истории сообщений.

    Дедуп по (title, file) — модель иногда повторяет вызов; сортировка по
    severity (critical→info). Источник — args tool-call, не текст модели.
    """
    findings: dict[tuple[str, str | None], dict[str, Any]] = {}
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls or []:
            if call.get("name") != FINDING_TOOL:
                continue
            finding = finding_from_args(call.get("args") or {})
            if not finding["title"]:
                continue
            findings[(finding["title"], finding["file"])] = finding
    return sorted(findings.values(), key=lambda f: _SEVERITY_ORDER.get(f["severity"], 99))


_TASK_TERMINAL_TYPES = {
    "task_completed",
    "task_failed",
    "task_cancelled",
    "task_timed_out",
}


def collect_findings_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Полный набор Находок Рана из persisted-событий: Лид + Сабагенты.

    Лид — из updates-событий (report_finding-tool_calls, полные args); Сабагенты —
    из task_terminal-событий (готовые camelCase-Находки). Каждая несёт `agent`
    (кто нашёл). Дедуп по (title, file), сортировка по severity.
    """
    merged: dict[tuple[str, str | None], dict[str, Any]] = {}

    def add(finding: dict[str, Any], agent: str) -> None:
        if not finding.get("title"):
            return
        merged[(finding["title"], finding.get("file"))] = {**finding, "agent": agent}

    for event in events:
        payload = event.get("payload") or {}
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        dtype = data.get("type")
        if dtype in _TASK_TERMINAL_TYPES:
            agent = data.get("subagent_type") or "subagent"
            for finding in data.get("findings") or []:
                add(dict(finding), agent)
            continue
        # updates-событие Лида: {node: {"messages": [...]}}
        if event.get("kind") == "updates":
            for value in data.values():
                if not isinstance(value, dict):
                    continue
                for msg in value.get("messages") or []:
                    if not isinstance(msg, dict) or msg.get("type") != "ai":
                        continue
                    for call in msg.get("tool_calls") or []:
                        if call.get("name") == FINDING_TOOL:
                            add(finding_from_args(call.get("args") or {}), "lead")
    return sorted(merged.values(), key=lambda f: _SEVERITY_ORDER.get(f["severity"], 99))


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводка: распределение по severity + счётчики."""
    counts = dict.fromkeys(SEVERITIES, 0)
    for finding in findings:
        sev = finding.get("severity", "info")
        counts[sev] = counts.get(sev, 0) + 1
    agents = {f.get("agent") for f in findings if f.get("agent")}
    return {
        "severityCounts": counts,
        "total": len(findings),
        "agents": sorted(a for a in agents if a),
    }
