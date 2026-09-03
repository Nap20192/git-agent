"""web_search: веб-поиск (Tavily) для ВНЕШНИХ фактов — advisories, CVE/GHSA, документация
и известные уязвимости зависимостей; репо ищут grep_code/read_file, не поиском.

Ходит с хоста раннера (httpx, Bearer TAVILY_API_KEY), не из Песочницы; ключ пуст ⇒
тул не регистрируется (см. core/tools/sandbox.build_sandbox_tools). Ошибки — текстом модели.
"""

from __future__ import annotations

import httpx
from langchain_core.tools import BaseTool, tool

TAVILY_URL = "https://api.tavily.com/search"
SEARCH_TIMEOUT_SECONDS = 30.0
MAX_RESULTS = 10
SNIPPET_CHARS = 700


def format_results(payload: dict) -> str:
    results = payload.get("results") or []
    if not results:
        return "web_search: no results"
    lines = []
    for i, r in enumerate(results, 1):
        snippet = " ".join(str(r.get("content") or "").split())[:SNIPPET_CHARS]
        lines.append(f"{i}. {r.get('title') or '(no title)'}\n   {r.get('url')}\n   {snippet}")
    return "\n".join(lines)


def build_web_search_tool(
    api_key: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> BaseTool:
    @tool
    async def web_search(query: str, max_results: int = 5) -> str:
        """Search the web (Tavily) for EXTERNAL facts: security advisories, CVE/GHSA
        entries, known vulnerabilities of a dependency version, library docs. Returns
        ranked results with title, URL and a snippet; open a result with browse(url).
        Never use it to search the repository itself — use grep_code/read_file.

        Args:
            query: search query (name the library + version + "CVE"/"advisory" for vulns).
            max_results: 1..10 results (default 5).
        """
        q = query.strip()
        if not q:
            return "web_search: query is required"
        n = max(1, min(int(max_results), MAX_RESULTS))
        try:
            async with httpx.AsyncClient(
                timeout=SEARCH_TIMEOUT_SECONDS, transport=transport
            ) as client:
                resp = await client.post(
                    TAVILY_URL,
                    json={"query": q, "max_results": n},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except httpx.HTTPError as exc:
            return f"web_search failed: {type(exc).__name__}: {exc}"
        if resp.status_code != 200:
            return f"web_search failed: HTTP {resp.status_code}: {resp.text[:300]}"
        return format_results(resp.json())

    return web_search
