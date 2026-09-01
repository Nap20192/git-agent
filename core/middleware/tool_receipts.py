"""ToolReceiptMiddleware — рантайм-слой квитанций (устанавливается ТОЛЬКО на
детские цепочки; обязан быть самым внешним wrap_tool_call).

Инварианты:
- штамп ПЕРЕЗАПИСЫВАЕТ ключ безусловно (анти-подделка: тул не может
  сфабриковать «своё доказательство»);
- никогда не блокирует исполнение тула (сбой штамповки — warning в лог);
- леджер инжектится в ЗАПРОС модели (после ведущих system-сообщений),
  НЕ в состояние — нет стейл-аккумуляции и второго SystemMessage;
- на каждый AIMessage ответа штампуется снапшот ОТРЕНДЕРЕННОГО подмножества
  леджера — по нему верифицируются цитаты этого хода (перенумерация после
  компакции не ломает резолв).
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from core.subagents.receipts import (
    TOOL_RECEIPT_KEY,
    TOOL_RECEIPT_LEDGER_KEY,
    extract_tool_receipts,
    make_tool_receipt,
    render_tool_receipts_with_snapshot,
)
from pkg.logger import get_logger

log = get_logger(__name__)


class ToolReceiptMiddleware(AgentMiddleware):
    def _stamp(self, request: Any, result: Any) -> Any:
        try:
            if isinstance(result, ToolMessage):
                result.additional_kwargs = {
                    **(result.additional_kwargs or {}),
                    TOOL_RECEIPT_KEY: make_tool_receipt(request.tool_call, result),
                }
            elif hasattr(result, "update") and isinstance(result.update, dict):
                # Command: штамповать только сообщения этого tool_call
                for message in result.update.get("messages", []):
                    if isinstance(
                        message, ToolMessage
                    ) and message.tool_call_id == request.tool_call.get("id"):
                        message.additional_kwargs = {
                            **(message.additional_kwargs or {}),
                            TOOL_RECEIPT_KEY: make_tool_receipt(request.tool_call, message),
                        }
        except Exception:
            log.warning("receipt stamping failed", exc_info=True)
        return result

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        return self._stamp(request, handler(request))

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        return self._stamp(request, await handler(request))

    def _inject_ledger(self, request: Any) -> tuple[Any, list[dict]]:
        receipts = extract_tool_receipts(list(request.messages))
        if not receipts:
            return request, []
        rendered, snapshot = render_tool_receipts_with_snapshot(receipts)
        if not rendered:
            return request, []
        messages = list(request.messages)
        insert_at = 0
        while insert_at < len(messages) and isinstance(messages[insert_at], SystemMessage):
            insert_at += 1
        # human-роль, не system: строгие провайдеры режут второй system
        messages.insert(insert_at, HumanMessage(content=rendered))
        return request.override(messages=messages), [dict(r) for r in snapshot]

    @staticmethod
    def _stamp_response(response: Any, snapshot: list[dict]) -> Any:
        if not snapshot:
            return response
        try:
            for message in getattr(response, "result", None) or []:
                if isinstance(message, AIMessage):
                    message.additional_kwargs = {
                        **(message.additional_kwargs or {}),
                        TOOL_RECEIPT_LEDGER_KEY: snapshot,
                    }
        except Exception:
            log.warning("ledger snapshot stamping failed", exc_info=True)
        return response

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        request, snapshot = self._inject_ledger(request)
        return self._stamp_response(handler(request), snapshot)

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        request, snapshot = self._inject_ledger(request)
        return self._stamp_response(await handler(request), snapshot)
