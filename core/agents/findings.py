"""Security-находки и инструменты агента: report_finding, load_skill.

Модель Находки — по образцу strix, адаптирована под статический анализ кода
(файл/строки вместо endpoint/method). Находки НЕ хранятся в коллекторе:
report_finding только валидирует и подтверждает, а извлекаются они из
tool_calls в истории сообщений хода (per-run state, без утечки между Ранами).
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, tool

SEVERITIES = ("critical", "high", "medium", "low", "info")
_FINDING_TOOL = "report_finding"


@tool(_FINDING_TOOL)
def report_finding(
    title: str,
    severity: str,
    description: str,
    file: str = "",
    start_line: int = 0,
    end_line: int = 0,
    cwe: str = "",
    cve: str = "",
    impact: str = "",
    evidence: str = "",
    remediation: str = "",
    confidence: str = "",
) -> str:
    """Зафиксировать security-находку по коду репозитория.

    Вызывай по одному разу на подтверждённую уязвимость, опираясь на реально
    прочитанный код (не на догадку). Находки собираются в Отчёт Рана.

    Args:
        title: краткое название (например «SQL-инъекция в user login»).
        severity: одно из critical/high/medium/low/info.
        description: что за уязвимость и почему это уязвимость.
        file: путь к файлу внутри репозитория (если применимо).
        start_line: первая строка уязвимого участка (0 — неизвестно).
        end_line: последняя строка участка (0 — неизвестно).
        cwe: класс уязвимости, например «CWE-89».
        cve: связанный CVE, если есть, например «CVE-2024-1234».
        impact: к чему приводит эксплуатация.
        evidence: цитата уязвимого кода / доказательство.
        remediation: как исправить.
        confidence: уверенность (high/medium/low) с кратким обоснованием.
    """
    sev = severity.lower().strip()
    if sev not in SEVERITIES:
        return f"report_finding: bad severity {severity!r}; use one of {', '.join(SEVERITIES)}"
    if not title.strip() or not description.strip():
        return "report_finding: title and description are required"
    where = f" [{file}:{start_line}]" if file else ""
    return f"recorded {sev} finding: {title.strip()}{where}"


def _finding_from_args(args: dict[str, Any]) -> dict[str, Any]:
    sev = str(args.get("severity", "")).lower().strip()
    return {
        "title": str(args.get("title", "")).strip(),
        "severity": sev if sev in SEVERITIES else "info",
        "description": str(args.get("description", "")).strip(),
        "file": str(args.get("file", "")).strip() or None,
        "startLine": int(args.get("start_line") or 0) or None,
        "endLine": int(args.get("end_line") or 0) or None,
        "cwe": str(args.get("cwe", "")).strip() or None,
        "cve": str(args.get("cve", "")).strip() or None,
        "impact": str(args.get("impact", "")).strip() or None,
        "evidence": str(args.get("evidence", "")).strip() or None,
        "remediation": str(args.get("remediation", "")).strip() or None,
        "confidence": str(args.get("confidence", "")).strip() or None,
    }


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
            if call.get("name") != _FINDING_TOOL:
                continue
            finding = _finding_from_args(call.get("args") or {})
            if not finding["title"]:
                continue
            findings[(finding["title"], finding["file"])] = finding
    return sorted(findings.values(), key=lambda f: _SEVERITY_ORDER.get(f["severity"], 99))


def build_security_tools() -> list[BaseTool]:
    """Инструменты, общие для Лида и Сабагентов в security-режиме."""
    from core.skills import load_skills, validate_requested_skills

    @tool
    def load_skill(skills: list[str]) -> str:
        """Загрузить справку по классам уязвимостей / технологиям в текущий ход.

        Зови перед проверкой конкретной техники, когда нужна точная методика
        (синтаксис, места, признаки). Содержимое приходит как справка, промпт
        не меняется.

        Args:
            skills: имена skills (например ["sql_injection", "authentication_jwt"]).
                Максимум 5. Каталог — в системном промпте.
        """
        err = validate_requested_skills(list(skills or []))
        if err:
            return f"load_skill: {err}"
        contents = load_skills(list(skills))
        if not contents:
            return "load_skill: nothing loaded"
        return "\n\n---\n\n".join(f"## Skill: {name}\n\n{body}" for name, body in contents.items())

    return [report_finding, load_skill]
