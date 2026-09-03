"""MCP-тулинг: тегирование внешних тулов и deferred-каталог `tool_search`."""

from core.tools.mcp.metadata import MCP_TOOL_METADATA_KEY, is_mcp_tool, tag_mcp_tool
from core.tools.mcp.tool_search import (
    DeferredToolCatalog,
    DeferredToolSetup,
    assemble_deferred_tools,
    build_deferred_tool_setup,
    build_tool_search_tool,
    get_deferred_tools_prompt_section,
)

__all__ = [
    "MCP_TOOL_METADATA_KEY",
    "DeferredToolCatalog",
    "DeferredToolSetup",
    "assemble_deferred_tools",
    "build_deferred_tool_setup",
    "build_tool_search_tool",
    "get_deferred_tools_prompt_section",
    "is_mcp_tool",
    "tag_mcp_tool",
]
