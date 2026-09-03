"""Исключение тула → error-ToolMessage: ран продолжается, а не падает."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp

from pkg.logger import get_logger

log = get_logger(__name__)

_DETAIL_MAX_CHARS = 500


class ToolErrorHandlingMiddleware(AgentMiddleware):
    def _to_error_message(self, request: Any, exc: Exception) -> ToolMessage:
        name = str(request.tool_call.get("name") or "unknown")
        detail = str(exc)[:_DETAIL_MAX_CHARS]
        log.warning(
            "middleware=tool_error_handling converted tool exception",
            tool=name,
            tool_call_id=request.tool_call.get("id"),
            exc_type=type(exc).__name__,
            detail=detail,
        )
        return ToolMessage(
            content=(
                f"Error: Tool '{name}' failed with {type(exc).__name__}: {detail}."
                " You may retry, adjust arguments, or try another approach."
            ),
            name=name,
            tool_call_id=str(request.tool_call.get("id") or ""),
            status="error",
        )

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        try:
            return handler(request)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            return self._to_error_message(request, exc)

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        try:
            return await handler(request)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            return self._to_error_message(request, exc)
