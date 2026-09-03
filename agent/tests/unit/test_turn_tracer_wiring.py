"""Сквозная проводка TurnTracer: create_agent → ToolNode → тул; коллбэк из config
наследуется вложенными вызовами, сводка видит и LLM, и тул."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from core.agents.factory import build_agent
from core.tracing import TurnTracer


class _ScriptedModel(BaseChatModel):
    script: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **_: Any
    ) -> ChatResult:
        message = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


@tool
def echo(text: str) -> str:
    """Вернуть текст."""
    return text.upper()


def test_tracer_sees_llm_and_tool_through_agent_graph():
    model = _ScriptedModel(
        script=[
            AIMessage(
                content="",
                tool_calls=[{"name": "echo", "args": {"text": "hi"}, "id": "c1"}],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            ),
            AIMessage(content="done"),
        ]
    )
    agent = build_agent(model, [echo], checkpointer=False, name="lead")
    tracer = TurnTracer()

    async def run():
        async for _ in agent.astream(
            {"messages": [("user", "go")]}, config={"callbacks": [tracer]}, stream_mode="updates"
        ):
            pass

    asyncio.run(run())
    s = tracer.summary()
    assert s["llm_calls"] == 2 and s["input_tokens"] == 10
    assert s["tool_calls"] == {"echo": 1} and s["by_agent"]["lead"]["echo"] == 1
