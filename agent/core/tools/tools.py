"""Сборщик get_available_tools: config > builtins > mcp, host-bash фильтр."""

from core.tools.mcp_metadata import tag_mcp_tool
from core.tools.sync import ensure_sync_invocable_tool


def _is_host_bash_tool(cfg) -> bool:
    return (
        getattr(cfg, "group", None) == "bash"
        or getattr(cfg, "use", None) == "core.tools.sandbox:bash_tool"
    )


def get_available_tools(config_entries, builtin_tools, mcp_tools=(), *, host_bash_allowed=True):
    """config_entries: список (cfg, tool), как в реальном резолве config.yaml."""
    if not host_bash_allowed:
        config_entries = [(cfg, t) for cfg, t in config_entries if not _is_host_bash_tool(cfg)]
    config_tools = [t for _, t in config_entries]
    for t in mcp_tools:
        tag_mcp_tool(t)
    all_tools = [ensure_sync_invocable_tool(t) for t in [*config_tools, *builtin_tools, *mcp_tools]]
    seen, unique = set(), []
    for t in all_tools:
        if t.name not in seen:
            unique.append(t)
            seen.add(t.name)
    return unique
