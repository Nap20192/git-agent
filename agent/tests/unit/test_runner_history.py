"""Санация висящих tool_calls в треде Экземпляра (core/runner/history.py)."""

import asyncio

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

from core.agents.factory import build_agent
from core.runner.history import CANCELLED_TOOL_RESULT, repair_dangling_tool_calls

CONFIG = {"configurable": {"thread_id": "t1"}}


@tool
def probe(x: str) -> str:
    """stub."""
    return x


def _graph():
    return build_agent(GenericFakeChatModel(messages=iter([])), [probe], checkpointer=MemorySaver())


def _call(cid: str) -> dict:
    return {"id": cid, "name": "probe", "args": {"x": cid}, "type": "tool_call"}


async def _seed(graph, messages):
    # состояние, которое оставляет отменённый ход: AIMessage записан узлом model,
    # tools до ToolMessage не дошёл
    await graph.aupdate_state(CONFIG, {"messages": messages}, as_node="model")


async def _messages(graph):
    return list((await graph.aget_state(CONFIG)).values["messages"])


def _tool_ids(messages):
    return [m.tool_call_id for m in messages if isinstance(m, ToolMessage)]


def test_dangling_tail_gets_tool_message_idempotently():
    async def run():
        graph = _graph()
        await _seed(
            graph, [HumanMessage("hi", id="h1"), AIMessage("", tool_calls=[_call("c1")], id="a1")]
        )
        assert await repair_dangling_tool_calls(graph, CONFIG) == 1
        msgs = await _messages(graph)
        assert [type(m).__name__ for m in msgs] == ["HumanMessage", "AIMessage", "ToolMessage"]
        assert msgs[-1].tool_call_id == "c1" and msgs[-1].content == CANCELLED_TOOL_RESULT
        assert await repair_dangling_tool_calls(graph, CONFIG) == 0
        assert len(await _messages(graph)) == 3

    asyncio.run(run())


def test_clean_thread_untouched():
    async def run():
        graph = _graph()
        seed = [
            HumanMessage("hi", id="h1"),
            AIMessage("", tool_calls=[_call("c1")], id="a1"),
            ToolMessage("ok", tool_call_id="c1", id="t1"),
            AIMessage("done", id="a2"),
        ]
        await _seed(graph, seed)
        assert await repair_dangling_tool_calls(graph, CONFIG) == 0
        assert await _messages(graph) == seed

    asyncio.run(run())


def test_empty_thread_is_noop():
    async def run():
        assert await repair_dangling_tool_calls(_graph(), CONFIG) == 0

    asyncio.run(run())


def test_two_dangling_calls_in_one_message():
    async def run():
        graph = _graph()
        await _seed(graph, [AIMessage("", tool_calls=[_call("c1"), _call("c2")], id="a1")])
        assert await repair_dangling_tool_calls(graph, CONFIG) == 2
        assert _tool_ids(await _messages(graph)) == ["c1", "c2"]

    asyncio.run(run())


def test_dangling_in_middle_is_answered_in_place():
    # тред, уже «сломанный» упавшим ходом: за висящим AIMessage лежит HumanMessage
    async def run():
        graph = _graph()
        await _seed(
            graph,
            [
                HumanMessage("hi", id="h1"),
                AIMessage("", tool_calls=[_call("c1")], id="a1"),
                HumanMessage("again", id="h2"),
            ],
        )
        assert await repair_dangling_tool_calls(graph, CONFIG) == 1
        msgs = await _messages(graph)
        assert [m.id for m in msgs if not isinstance(m, ToolMessage)] == ["h1", "a1", "h2"]
        assert isinstance(msgs[2], ToolMessage) and msgs[2].tool_call_id == "c1"
        assert msgs[3].id == "h2"
        assert await repair_dangling_tool_calls(graph, CONFIG) == 0

    asyncio.run(run())
