"""Нейтрализация framework-тегов в недоверенном выводе тулов."""

from __future__ import annotations

import re
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from pkg.logger import get_logger

log = get_logger(__name__)

SANITIZED_KEY = "sanitized"

# Тулы, чей вывод — недоверенный контент (содержимое чужого репозитория)
DEFAULT_UNTRUSTED_TOOLS = frozenset({"sandbox_run", "read_file"})

# Денилист «как класс»: наши framework-теги + типовые инъекционные
_FRAMEWORK_TAGS = (
    "system-reminder",
    "report_contract",
    "acceptance_criteria",
    "durable_context_data",
    "system",
    "instruction",
    "override",
)
_TAG_RE = re.compile(rf"<(/?)({'|'.join(re.escape(t) for t in _FRAMEWORK_TAGS)})\b", re.IGNORECASE)


def neutralize_framework_tags(text: str) -> tuple[str, int]:
    """Экранировать открытие/закрытие денилист-тегов; вернуть (текст, счётчик)."""
    return _TAG_RE.subn(r"&lt;\1\2", text)


class ToolResultSanitizationMiddleware(AgentMiddleware):
    def __init__(self, untrusted_tools: frozenset[str] = DEFAULT_UNTRUSTED_TOOLS) -> None:
        super().__init__()
        self._untrusted = untrusted_tools

    def _sanitize(self, request: Any, result: Any) -> Any:
        tool_name = str(request.tool_call.get("name") or "")
        if tool_name not in self._untrusted:
            return result
        try:
            messages = (
                [result]
                if isinstance(result, ToolMessage)
                else [
                    m
                    for m in (getattr(result, "update", None) or {}).get("messages", [])
                    if isinstance(m, ToolMessage) and m.tool_call_id == request.tool_call.get("id")
                ]
            )
            for message in messages:
                if not isinstance(message.content, str):
                    continue
                cleaned, hits = neutralize_framework_tags(message.content)
                if hits:
                    message.content = cleaned
                    message.additional_kwargs = {
                        **(message.additional_kwargs or {}),
                        SANITIZED_KEY: True,
                    }
                    log.warning(
                        "middleware=tool_result_sanitization neutralized framework tags",
                        tool=tool_name,
                        tool_call_id=request.tool_call.get("id"),
                        tags_neutralized=hits,
                    )
        except Exception:
            log.exception("middleware=tool_result_sanitization failed; passing raw")
        return result

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        return self._sanitize(request, handler(request))

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        return self._sanitize(request, await handler(request))
