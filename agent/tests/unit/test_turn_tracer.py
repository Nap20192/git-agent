"""TurnTracer: длительность и токены LLM-вызова, тул-вызовы по агентам, сводка."""

import asyncio
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from core.tracing import TurnTracer


def test_tracer_accounts_llm_and_tools_per_agent():
    async def run():
        t = TurnTracer()
        llm, tool, sub_tool = uuid4(), uuid4(), uuid4()
        await t.on_chat_model_start({}, [[]], run_id=llm, tags=[])
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "sandbox_run", "args": {"command": "ls"}, "id": "c1"}],
            usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
        )
        await t.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]), run_id=llm)
        await t.on_tool_start(
            {"name": "sandbox_run"}, "ls", run_id=tool, tags=[], inputs={"command": "ls"}
        )
        await t.on_tool_end("a\nb", run_id=tool)
        await t.on_tool_start(
            {"name": "read_file"}, "/x", run_id=sub_tool, tags=["subagent:general-purpose"]
        )
        await t.on_tool_error(RuntimeError("no such file"), run_id=sub_tool)
        return t.summary()

    s = asyncio.run(run())
    assert s["llm_calls"] == 1 and s["input_tokens"] == 120 and s["output_tokens"] == 30
    assert s["tool_calls"] == {"sandbox_run": 1} and s["tool_errors"] == 1
    assert s["by_agent"] == {"lead": {"llm_calls": 1, "sandbox_run": 1}}
    assert s["llm_ms"] >= 0 and set(s["tool_ms"]) == {"sandbox_run"}
