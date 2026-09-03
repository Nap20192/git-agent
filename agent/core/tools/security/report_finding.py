"""Тул report_finding + набор security-тулов, общий для Лида и Сабагентов."""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from core.tools.security.findings import FINDING_TOOL, validate_finding
from core.tools.security.load_skill import build_load_skill_tool


@tool(FINDING_TOOL)
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
    error = validate_finding(title, severity, description)
    if error:
        return error
    where = f" [{file}:{start_line}]" if file else ""
    return f"recorded {severity.lower().strip()} finding: {title.strip()}{where}"


def build_security_tools() -> list[BaseTool]:
    """Инструменты, общие для Лида и Сабагентов в security-режиме."""
    return [report_finding, build_load_skill_tool()]
