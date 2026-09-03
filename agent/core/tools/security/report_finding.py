"""Тул report_finding + набор security-тулов, общий для Лида и Сабагентов."""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from core.tools.security.findings import CATEGORIES, FINDING_TOOL, validate_finding
from core.tools.security.load_skill import build_load_skill_tool


@tool(FINDING_TOOL)
def report_finding(
    title: str,
    severity: str,
    description: str = "",
    file: str = "",
    start_line: int = 0,
    end_line: int = 0,
    cwe: str = "",
    cve: str = "",
    impact: str = "",
    evidence: str = "",
    remediation: str = "",
    confidence: str = "",
    category: str = "other",
    references: list[str] | None = None,
) -> str:
    """Зафиксировать security-находку по коду репозитория.

    Вызывай по одному разу на подтверждённую уязвимость, опираясь на реально
    прочитанный код (не на догадку). Заполняй ВСЕ поля, которые знаешь: title,
    description, impact, confidence, category, cwe, references — из них строится
    структурированный Отчёт. Автора/коммит строк (blame) НЕ передавай — система
    определит сама по file и start_line.

    Args:
        title: краткий заголовок (например «SQL-инъекция в user login»).
        severity: одно из critical/high/medium/low/info.
        description: что уязвимо и почему (трейс source→sink).
        file: путь к файлу внутри репозитория (обязателен).
        start_line: первая строка уязвимого участка (0 — неизвестно).
        end_line: последняя строка участка (0 — неизвестно).
        cwe: класс уязвимости, например «CWE-89».
        cve: связанный CVE, если есть, например «CVE-2024-1234».
        impact: последствия эксплуатации.
        evidence: цитата уязвимого кода / доказательство.
        remediation: конкретное исправление.
        confidence: high/medium/low (static-only трейс — максимум medium).
        category: одно из injection/auth/crypto/secrets/deps/config/xss/ssrf/path/logic/other.
        references: ссылки (advisory, CWE, документация) — список URL.
    """
    error = validate_finding(title, severity, file)
    if error:
        return error
    where = f" [{file}:{start_line}]" if start_line else f" [{file}]"
    note = "" if category.lower().strip() in CATEGORIES else " (category normalized to 'other')"
    return f"recorded {severity.lower().strip()} finding: {title.strip()}{where}{note}"


def build_security_tools() -> list[BaseTool]:
    """Инструменты, общие для Лида и Сабагентов в security-режиме."""
    return [report_finding, build_load_skill_tool()]
