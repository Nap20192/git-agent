"""Тегирование MCP-тулов. Leaf-модуль: зависит только от BaseTool —
и загрузчик, и читатели импортируют его без циклов; магическая строка
живёт ровно в одном месте."""

from langchain_core.tools import BaseTool

MCP_TOOL_METADATA_KEY = "git_agent_mcp"


def tag_mcp_tool(t: BaseTool) -> BaseTool:
    t.metadata = {**(t.metadata or {}), MCP_TOOL_METADATA_KEY: True}
    return t


def is_mcp_tool(t: BaseTool) -> bool:
    # строгая проверка is True: крафтовое truthy-значение — не тег
    return (getattr(t, "metadata", None) or {}).get(MCP_TOOL_METADATA_KEY) is True
