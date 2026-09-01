"""Тулинг агента — lean-ядро по образцу deerflow/tools.

Покрывает: MCP-тегирование, sync-обёртку async-тулов, DeferredToolCatalog
(select:/+/regex-поиск, hash), fail-closed сборку deferred, промпт-секцию
с экранированием и get_available_tools (host-bash фильтр, приоритетный дедуп).
Пропущено: subagents/batch/ACP/skills — не ядро сборки (сабагенты в git-agent
живут своей системой: core/subagents/).
"""

from core.tools.mcp_metadata import MCP_TOOL_METADATA_KEY, is_mcp_tool, tag_mcp_tool
from core.tools.sync import make_sync_tool_wrapper
from core.tools.tool_search import (
    DeferredToolCatalog,
    DeferredToolSetup,
    assemble_deferred_tools,
    build_deferred_tool_setup,
    build_tool_search_tool,
    get_deferred_tools_prompt_section,
)
from core.tools.tools import get_available_tools

__all__ = [
    "MCP_TOOL_METADATA_KEY",
    "DeferredToolCatalog",
    "DeferredToolSetup",
    "assemble_deferred_tools",
    "build_deferred_tool_setup",
    "build_tool_search_tool",
    "get_available_tools",
    "get_deferred_tools_prompt_section",
    "is_mcp_tool",
    "make_sync_tool_wrapper",
    "tag_mcp_tool",
]
