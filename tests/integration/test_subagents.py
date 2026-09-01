"""End-to-end делегация: лид → task → реальный create_agent-ребёнок.

Фейковые модель и песочница, но настоящий граф create_agent, настоящие
middleware (receipts) и настоящий тул task.
"""

import asyncio
import dataclasses

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from core.agents.factory import build_agent
from core.agents.subagents import SubagentCapacity, build_task_tool
from core.agents.subagents.contract import read_subagent_result_metadata
from core.agents.subagents.registry import BUILTIN_SUBAGENTS, GENERAL_PURPOSE
from core.agents.tools import build_sandbox_tools


class FakeSandbox:
    repo_dir = "/repo"

    def __init__(self, outputs: dict[str, str] | None = None):
        self.outputs = outputs or {}
        self.commands: list[str] = []

    async def run(self, command: str, *, timeout_seconds=None) -> str:
        self.commands.append(command)
        return self.outputs.get(command, f"output of: {command}")

    async def close(self) -> None:
        pass


def _ai_tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[
        {"name": name, "args": args, "id": call_id, "type": "tool_call"}
    ])


class ToolFakeModel(GenericFakeChatModel):
    """Фейк с поддержкой bind_tools (игнорирует биндинг).

    Лид и ребёнок делят инстанс — очередь сообщений общая, реплики
    скриптуются в порядке фактических вызовов модели."""

    def bind_tools(self, tools, **kwargs):
        return self



def _lead_with_task(lead_script, sandbox, capacity=None):
    model = ToolFakeModel(messages=iter(lead_script))
    task_tool = build_task_tool(
        sandbox=sandbox, model=model, capacity=capacity or SubagentCapacity()
    )
    tools = [*build_sandbox_tools(sandbox), task_tool]
    lead = build_agent(model, tools, checkpointer=False, name="lead")
    return lead


def test_delegation_end_to_end_with_receipts_verdict():
    async def main():
        sandbox = FakeSandbox()
        # порядок вызовов модели: лид(1) → ребёнок(2,3) → лид(4)
        script = [
            _ai_tool_call("task", {
                "description": "scan repo files",
                "prompt": "List repo files",
                "subagent_type": "general-purpose",
            }, "task-1"),
            _ai_tool_call("sandbox_run", {"command": "ls /repo"}, "child-1"),
            AIMessage(content="Я запустил ls [r1 sandbox_run]. Файлы: main.py."),
            AIMessage(content="Итог: в репозитории main.py."),
        ]
        lead = _lead_with_task(script, sandbox)

        events = []
        final = None
        async for mode, chunk in lead.astream(
            {"messages": [HumanMessage(content="analyze")]},
            stream_mode=["values", "custom"],
        ):
            if mode == "custom":
                events.append(chunk)
            else:
                final = chunk

        tool_messages = [m for m in final["messages"]
                         if isinstance(m, ToolMessage) and m.name == "task"]
        assert len(tool_messages) == 1
        meta = read_subagent_result_metadata(tool_messages[0].additional_kwargs)
        assert meta["status"] == "completed"
        assert "запустил ls" in meta["result_brief"]
        # квитанция дошла до лида, цитата разрезолвилась
        assert len(meta["tool_receipts"]) == 1
        assert meta["tool_receipts"][0]["tool_name"] == "sandbox_run"
        verdict = meta["receipt_verdict"]
        assert verdict["citation_resolved"] and verdict["resolved"] == ["r1"]
        assert "1 resolved" in tool_messages[0].content

        kinds = [e["type"] for e in events]
        assert kinds[0] == "task_started" and kinds[-1] == "task_completed"
        assert "task_running" in kinds
        # песочница реально исполнила команду ребёнка
        assert "ls /repo" in sandbox.commands

    asyncio.run(main())


def test_unknown_subagent_type_returns_failed_result():
    async def main():
        sandbox = FakeSandbox()
        script = [
            _ai_tool_call("task", {
                "description": "x", "prompt": "y", "subagent_type": "martian",
            }, "task-1"),
            AIMessage(content="ok, no delegation"),
        ]
        lead = _lead_with_task(script, sandbox)
        final = await lead.ainvoke({"messages": [HumanMessage(content="go")]})
        tm = next(m for m in final["messages"]
                  if isinstance(m, ToolMessage) and m.name == "task")
        meta = read_subagent_result_metadata(tm.additional_kwargs)
        assert meta["status"] == "failed"
        assert "general-purpose" in meta["error"]  # список доступных типов

    asyncio.run(main())


def test_timeout_yields_timed_out_status():
    async def main():
        class SlowSandbox(FakeSandbox):
            async def run(self, command: str, *, timeout_seconds=None) -> str:
                await asyncio.sleep(10)
                return ""

        BUILTIN_SUBAGENTS["snail"] = dataclasses.replace(
            GENERAL_PURPOSE, name="snail", timeout_seconds=0.3
        )
        try:
            sandbox = SlowSandbox()
            script = [
                _ai_tool_call("task", {
                    "description": "x", "prompt": "y", "subagent_type": "snail",
                }, "task-1"),
                _ai_tool_call("sandbox_run", {"command": "sleep"}, "child-1"),
                AIMessage(content="unreached"),
                AIMessage(content="lead final"),
            ]
            lead = _lead_with_task(script, sandbox)
            final = await lead.ainvoke({"messages": [HumanMessage(content="go")]})
            tm = next(m for m in final["messages"]
                      if isinstance(m, ToolMessage) and m.name == "task")
            meta = read_subagent_result_metadata(tm.additional_kwargs)
            assert meta["status"] == "timed_out"
            assert "Timed Out" in tm.content
        finally:
            BUILTIN_SUBAGENTS.pop("snail", None)

    asyncio.run(main())


def test_turn_cap_produces_stop_reason():
    async def main():
        BUILTIN_SUBAGENTS["twoturns"] = dataclasses.replace(
            GENERAL_PURPOSE, name="twoturns", max_turns=2
        )
        try:
            sandbox = FakeSandbox()
            # ребёнок бесконечно зовёт тулы — упрётся в recursion_limit
            script = [
                _ai_tool_call("task", {
                    "description": "x", "prompt": "y", "subagent_type": "twoturns",
                }, "task-1"),
                _ai_tool_call("sandbox_run", {"command": "a"}, "c1"),
                _ai_tool_call("sandbox_run", {"command": "b"}, "c2"),
                _ai_tool_call("sandbox_run", {"command": "c"}, "c3"),
                AIMessage(content="lead final"),
            ]
            lead = _lead_with_task(script, sandbox)
            final = await lead.ainvoke({"messages": [HumanMessage(content="go")]})
            tm = next(m for m in final["messages"]
                      if isinstance(m, ToolMessage) and m.name == "task")
            meta = read_subagent_result_metadata(tm.additional_kwargs)
            assert meta["status"] in ("failed", "completed")
            assert meta["stop_reason"] == "turn_capped"
        finally:
            BUILTIN_SUBAGENTS.pop("twoturns", None)

    asyncio.run(main())


def test_capacity_rejection_is_failed_result():
    async def main():
        sandbox = FakeSandbox()
        capacity = SubagentCapacity(max_running=1, max_queued=0, queue_timeout_seconds=1)
        # занять единственный слот навсегда
        blocker = asyncio.Event()

        async def hold():
            async with capacity.slot():
                await blocker.wait()

        holder = asyncio.create_task(hold())
        await asyncio.sleep(0.01)
        script = [
            _ai_tool_call("task", {
                "description": "x", "prompt": "y", "subagent_type": "general-purpose",
            }, "task-1"),
            AIMessage(content="lead final"),
        ]
        lead = _lead_with_task(script, sandbox, capacity=capacity)
        final = await lead.ainvoke({"messages": [HumanMessage(content="go")]})
        tm = next(m for m in final["messages"]
                  if isinstance(m, ToolMessage) and m.name == "task")
        meta = read_subagent_result_metadata(tm.additional_kwargs)
        assert meta["status"] == "failed"
        assert "not admitted" in meta["error"]
        blocker.set()
        await holder

    asyncio.run(main())
