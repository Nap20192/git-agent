"""web_search (Tavily) герметично: Bearer, формат выдачи, ошибки текстом, регистрация по ключу."""

import asyncio
import json

import httpx

from core.tools.web import build_web_search_tool


def _tool(handler):
    return build_web_search_tool("tvly-x", transport=httpx.MockTransport(handler))


def test_web_search_formats_results_and_sends_bearer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "GHSA-1",
                        "url": "https://x/1",
                        "content": "  csrf   in   axios  " * 200,
                    },
                    {"title": None, "url": "https://x/2", "content": ""},
                ]
            },
        )

    out = asyncio.run(_tool(handler).ainvoke({"query": " axios CVE ", "max_results": 50}))
    assert seen["auth"] == "Bearer tvly-x"
    assert seen["body"] == {"query": "axios CVE", "max_results": 10}
    assert out.startswith("1. GHSA-1\n   https://x/1\n   csrf in axios")
    assert "2. (no title)\n   https://x/2" in out
    assert len(out) < 1200  # сниппет усечён


def test_web_search_errors_are_text():
    unauthorized = _tool(lambda r: httpx.Response(401, text="Unauthorized"))
    assert (
        asyncio.run(unauthorized.ainvoke({"query": "x"}))
        == "web_search failed: HTTP 401: Unauthorized"
    )

    def boom(_r):
        raise httpx.ConnectError("dns")

    assert asyncio.run(_tool(boom).ainvoke({"query": "x"})).startswith(
        "web_search failed: ConnectError"
    )
    assert asyncio.run(_tool(boom).ainvoke({"query": "  "})) == "web_search: query is required"
    assert (
        asyncio.run(
            _tool(lambda r: httpx.Response(200, json={"results": []})).ainvoke({"query": "x"})
        )
        == "web_search: no results"
    )


def test_web_search_registered_only_with_key(monkeypatch):
    from core.config import settings
    from core.tools.sandbox import build_sandbox_tools
    from tests.unit.test_sandbox_tools import FakeSandbox

    monkeypatch.setattr(settings, "tavily_api_key", "")
    assert "web_search" not in {t.name for t in build_sandbox_tools(FakeSandbox())}
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-x")
    assert "web_search" in {t.name for t in build_sandbox_tools(FakeSandbox())}
