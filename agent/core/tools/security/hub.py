"""Security-тулы раннера: report_finding/write_report с персистом в hub.findings/hub.reports.

Находка v2: модель даёт title/description/impact/confidence/category/references,
раннер САМ дописывает blame (`core/tools/security/blame.py`) по file+lineStart в
Песочнице и introducedBy по диапазону События. Отчёт — структура
(`core/tools/security/report.py`) в hub.reports.structured + markdown в summary.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from core.ports import Sandbox
from core.runner.events import PR_ACTIONS
from core.runner.ports import InstanceStore
from core.tools.security.blame import BlameResolver
from core.tools.security.findings import finding_from_args, validate_finding
from core.tools.security.load_skill import build_load_skill_tool
from core.tools.security.report import (
    ReportRange,
    ReportScope,
    WriteReportArgs,
    build_structured_report,
    render_report_markdown,
)
from core.tools.security.report_finding import report_finding


def build_hub_security_tools(
    store: InstanceStore,
    instance_id: int,
    event_id: int | None = None,
    *,
    sandbox: Sandbox | None = None,
    scope_range: tuple[str, str] | None = None,
    event_type: str = "",
    commit: str | None = None,
) -> list[BaseTool]:
    """report_finding/write_report, пишущие в hub.findings/hub.reports (тикет 001:
    «результат агент пишет в БД сам, через тулзу»). Схема и описание report_finding —
    канонические из report_finding, здесь добавляются blame и персист. Один набор
    инстансов на ход — общий для Лида и Сабагентов, поэтому `recorded` и кэш blame
    покрывают весь ход. scope_range — (before, after) диапазон изменений События для
    introducedBy; None — не определяется (full_scan, чат). commit — коммит События,
    попадает в scope и заголовок Отчёта (у full_scan диапазона нет, коммит есть)."""
    resolver = BlameResolver(sandbox, scope_range) if sandbox is not None else None
    recorded: list[dict[str, Any]] = []

    async def _report_finding(**kwargs: Any) -> str:
        result = report_finding.func(**kwargs)
        if validate_finding(
            kwargs.get("title", ""), kwargs.get("severity", ""), kwargs.get("file", "")
        ):
            return result  # текст ошибки валидации — модели
        finding = finding_from_args(kwargs)
        if resolver is not None and finding["file"] and finding["lineStart"]:
            # blame — от инструмента, не от модели (модель blame не передаёт; конфликт → инструмент)
            finding.update(
                await resolver.resolve(finding["file"], finding["lineStart"], finding["lineEnd"])
            )
        recorded.append(finding)
        await store.add_finding(instance_id, finding, event_id=event_id)  # Находка ↔ Событие хода
        if finding.get("blameCommit"):
            introduced = {"this_event": "introduced by this event", "earlier": "pre-existing"}.get(
                finding.get("introducedBy") or "", "origin unknown"
            )
            result += (
                f"; blame: {finding.get('blameAuthor') or '?'} @ {(finding.get('blameDate') or '')[:10]}"
                f" {finding['blameCommit'][:7]} — {introduced}"
            )
        return result

    persisting_report_finding = StructuredTool(
        name=report_finding.name,
        description=report_finding.description,
        args_schema=report_finding.args_schema,
        coroutine=_report_finding,
    )

    default_range = None
    if scope_range:  # PR — base...head (merge-base), остальное — before..after
        default_range = (
            ReportRange(base=scope_range[0], head=scope_range[1])
            if event_type in PR_ACTIONS
            else ReportRange(before=scope_range[0], after=scope_range[1])
        )
    default_scope = ReportScope(event_type=event_type, commit=commit, range=default_range)

    async def _write_report(**kwargs: Any) -> str:
        args = WriteReportArgs(**kwargs)
        if not args.summary.strip():
            return "write_report: summary is required"
        structured = build_structured_report(args, list(recorded), default_scope=default_scope)
        summary = render_report_markdown(structured)
        report_id = await store.add_report(
            instance_id, event_id=event_id, summary=summary, structured=structured
        )
        return f"report {report_id} saved ({len(recorded)} findings attached)"

    write_report = StructuredTool(
        name="write_report",
        description=(
            "Записать итоговый структурированный Отчёт хода в базу. Вызови ОДИН раз в конце:"
            " summary (резюме: что разобрано, общий риск, вердикт), scope (что было в скоупе),"
            " method (какие тулы/анализаторы применялись), top_risks, recommendations,"
            " limitations (что не проверено / open_proof_gap). Находки и счётчики по severity"
            " система приложит сама из report_finding этого хода."
        ),
        args_schema=WriteReportArgs,
        coroutine=_write_report,
    )

    return [persisting_report_finding, build_load_skill_tool(), write_report]
