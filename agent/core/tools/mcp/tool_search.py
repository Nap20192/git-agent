"""Deferred-каталог MCP-тулов: схемы не биндятся модели сразу."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from functools import cached_property

from langchain_core.tools import BaseTool, tool
from langchain_core.utils.function_calling import convert_to_openai_function

from core.tools.mcp.metadata import is_mcp_tool

MAX_RESULTS = 5


def _compile_catalog_regex(pattern: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(pattern), re.IGNORECASE)


@dataclass(frozen=True)  # без slots=True: cached_property пишет в __dict__
class DeferredToolCatalog:
    tools: tuple[BaseTool, ...]

    @cached_property
    def names(self) -> frozenset[str]:
        return frozenset(t.name for t in self.tools)

    @cached_property
    def hash(self) -> str:
        canon = [
            {"name": t.name, "schema": convert_to_openai_function(t)}
            for t in sorted(self.tools, key=lambda t: t.name)
        ]
        payload = json.dumps(canon, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def search(self, query: str) -> list[BaseTool]:
        query = query.strip()
        if not query:
            return []
        if query.startswith("select:"):
            wanted = {n.strip() for n in query[7:].split(",")}
            return [t for t in self.tools if t.name in wanted]
        if query.startswith("+"):
            parts = query[1:].split(None, 1)
            if not parts:
                return []
            required = parts[0].lower()
            candidates = [t for t in self.tools if required in t.name.lower()]
            if len(parts) > 1:
                rx = _compile_catalog_regex(parts[1])
                candidates.sort(
                    key=lambda t: len(rx.findall(f"{t.name} {t.description or ''}")), reverse=True
                )
            return candidates[:MAX_RESULTS]
        regex = _compile_catalog_regex(query)
        scored = [
            (2 if regex.search(t.name) else 1, t)
            for t in self.tools
            if regex.search(f"{t.name} {t.description or ''}")
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored][:MAX_RESULTS]


@dataclass(frozen=True)
class DeferredToolSetup:
    """Три поля двигаются как единица: все пустые или все заполнены."""

    tool_search_tool: BaseTool | None
    deferred_names: frozenset[str]
    catalog_hash: str | None


def build_tool_search_tool(catalog: DeferredToolCatalog) -> BaseTool:
    @tool
    def tool_search(query: str) -> str:
        """Fetch full schemas for deferred tools by query (select:/+prefix/keywords)."""
        matched = catalog.search(query)
        if not matched:
            return f"No tools found matching: {query}"
        return json.dumps([convert_to_openai_function(t) for t in matched], ensure_ascii=False)

    return tool_search


def build_deferred_tool_setup(
    candidate_tools: list[BaseTool], *, enabled: bool
) -> DeferredToolSetup:
    if not enabled:
        return DeferredToolSetup(None, frozenset(), None)
    deferred = [t for t in candidate_tools if is_mcp_tool(t)]
    if not deferred:
        return DeferredToolSetup(None, frozenset(), None)
    catalog = DeferredToolCatalog(tuple(deferred))
    return DeferredToolSetup(build_tool_search_tool(catalog), catalog.names, catalog.hash)


def assemble_deferred_tools(candidate_tools: list[BaseTool], *, enabled: bool):
    """Общая точка для всех билд-путей; fail-closed: deferral включён и MCP-"""
    setup = build_deferred_tool_setup(candidate_tools, enabled=enabled)
    if enabled and not setup.deferred_names and any(is_mcp_tool(t) for t in candidate_tools):
        raise RuntimeError(
            "tool_search enabled and MCP candidates exist, but no deferred set was"
            " recovered - refusing to bind MCP schemas (fail-closed)."
        )
    final = list(candidate_tools)
    if setup.tool_search_tool:
        final.append(setup.tool_search_tool)
    return final, setup


def get_deferred_tools_prompt_section(*, deferred_names: frozenset[str] = frozenset()) -> str:
    if not deferred_names:
        return ""
    names = "\n".join(html.escape(n, quote=False) for n in sorted(deferred_names))
    return f"<available-deferred-tools>\n{names}\n</available-deferred-tools>"
