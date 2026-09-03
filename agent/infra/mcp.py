"""Загрузка тулов внешних MCP-серверов (адаптер к внешнему миру)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from core.config import settings
from core.tools.mcp import tag_mcp_tool
from pkg.logger import get_logger

log = get_logger(__name__)


def _server_configs() -> dict[str, dict[str, Any]]:
    """{имя: конфиг MultiServerMCPClient} для сконфигурированных серверов."""
    configs: dict[str, dict[str, Any]] = {}
    path = settings.cve_mcp_path.strip()
    if path and Path(path).is_dir():
        env = {"REQUEST_TIMEOUT": "30", "MAX_RETRIES": "3"}
        if settings.nvd_api_key:
            env["NVD_API_KEY"] = settings.nvd_api_key
        configs["cve"] = {
            "transport": "stdio",
            "command": "uv",
            "args": ["run", "--project", path, "python", "-m", "cve_mcp.server"],
            "env": env,
        }
    return configs


async def load_mcp_tools() -> list[BaseTool]:
    """Тулы всех сконфигурированных MCP-серверов, помеченные как MCP."""
    configs = _server_configs()
    if not configs:
        return []
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(configs)
        tools = await client.get_tools()
    except Exception:
        log.warning("MCP tools unavailable; continuing without them", servers=list(configs))
        return []
    for tool in tools:
        tag_mcp_tool(tool)
    log.info("loaded MCP tools", count=len(tools), servers=list(configs))
    return list(tools)
