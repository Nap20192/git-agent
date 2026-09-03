"""Security-тулы раннера: report_finding/write_report с персистом в hub.findings/hub.reports."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool, tool

from core.runner.ports import InstanceStore
from core.tools.security.findings import finding_from_args, validate_finding
from core.tools.security.load_skill import build_load_skill_tool
from core.tools.security.report_finding import report_finding


def build_hub_security_tools(
    store: InstanceStore, instance_id: int, event_id: int | None
) -> list[BaseTool]:
    """report_finding/write_report, пишущие в hub.findings/hub.reports (тикет 001:
    «результат агент пишет в БД сам, через тулзу»). Схема и описание report_finding —
    канонические из report_finding, здесь только добавляется персист."""

    async def _report_finding(**kwargs: Any) -> str:
        result = report_finding.func(**kwargs)
        if (
            validate_finding(
                kwargs.get("title", ""), kwargs.get("severity", ""), kwargs.get("description", "")
            )
            is None
        ):
            await store.add_finding(instance_id, finding_from_args(kwargs))
        return result

    persisting_report_finding = StructuredTool(
        name=report_finding.name,
        description=report_finding.description,
        args_schema=report_finding.args_schema,
        coroutine=_report_finding,
    )

    @tool("write_report")
    async def write_report(summary: str) -> str:
        """Записать итоговый Отчёт обработки в базу.

        Вызови один раз в конце работы: связное резюме — что разобрано, общий
        риск, приоритеты. Находки к нему уже привязаны через report_finding.

        Args:
            summary: текст Отчёта (markdown допустим).
        """
        if not summary.strip():
            return "write_report: summary is required"
        report_id = await store.add_report(instance_id, event_id=event_id, summary=summary.strip())
        return f"report {report_id} saved"

    return [persisting_report_finding, build_load_skill_tool(), write_report]
