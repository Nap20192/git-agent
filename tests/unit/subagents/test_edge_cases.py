"""Edge cases системы сабагентов: границы, малформленные данные, моки."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from core.middleware.tool_receipts import ToolReceiptMiddleware
from core.subagents.contract import (
    SUBAGENT_METADATA_TEXT_MAX_CHARS,
    SubagentStatus,
    _truncate_head_tail,
    format_subagent_result_message,
    make_subagent_additional_kwargs,
    read_subagent_result_metadata,
)
from core.subagents.executor import (
    SubagentExecutor,
    _build_messages,
    _extract_final_result,
)
from core.subagents.receipts import (
    TOOL_RECEIPT_KEY,
    TOOL_RECEIPT_LEDGER_KEY,
    extract_citing_turn_receipts,
    extract_tool_receipts,
    make_tool_receipt,
    parse_citations,
    render_tool_receipts_with_snapshot,
    verify_receipt_citations,
)
from core.subagents.registry import GENERAL_PURPOSE
from core.subagents.steps import capture_new_step_messages
from core.tools.sandbox import SANDBOX_OUTPUT_MAX_CHARS, build_sandbox_tools

# -- contract: границы усечения ----------------------------------------------


def test_truncate_head_tail_boundaries():
    exact = "x" * SUBAGENT_METADATA_TEXT_MAX_CHARS
    assert _truncate_head_tail(exact) == exact  # ровно лимит — не трогаем
    over = "a" * 3000
    out = _truncate_head_tail(over)
    assert len(out) <= SUBAGENT_METADATA_TEXT_MAX_CHARS
    assert "\n...\n" in out


def test_completed_suppresses_error_field():
    kwargs = make_subagent_additional_kwargs(
        SubagentStatus.COMPLETED, result="ok", error="stale error"
    )
    assert "subagent_error" not in kwargs


def test_reader_rebounds_oversized_brief():
    meta = read_subagent_result_metadata(
        {
            "subagent_status": "completed",
            "subagent_result_brief": "y" * 10_000,  # злоумышленный оверсайз с провода
        }
    )
    assert len(meta["result_brief"]) <= SUBAGENT_METADATA_TEXT_MAX_CHARS


def test_failed_empty_error_renders_unknown():
    text = format_subagent_result_message(SubagentStatus.FAILED, error="")
    assert "Unknown error" in text


# -- receipts: малформленные входы --------------------------------------------


def test_make_receipt_tolerates_weird_inputs():
    # args не dict, content не строка, id/name отсутствуют
    msg = ToolMessage(content=["chunk", {"k": 1}], tool_call_id="c1")
    receipt = make_tool_receipt({"args": "not-a-dict"}, msg)
    assert receipt["tool_call_id"] == "" and receipt["tool_name"] == ""
    assert len(receipt["args_sha256"]) == 16
    assert receipt["output_bytes"] > 0


def test_render_hard_truncation_retains_nothing():
    receipts = extract_tool_receipts([_stamped(1)])
    rendered, retained = render_tool_receipts_with_snapshot(receipts, max_chars=50)
    # изуродованный рендер ни за что не ручается
    assert retained == []
    assert len(rendered) <= 50


def _stamped(i: int) -> ToolMessage:
    call = {"id": f"call_{i}", "name": "sandbox_run", "args": {"i": i}}
    msg = ToolMessage(content=f"out{i}", tool_call_id=f"call_{i}")
    msg.additional_kwargs = {TOOL_RECEIPT_KEY: make_tool_receipt(call, msg)}
    return msg


def test_citing_snapshot_may_start_mid_ledger():
    # снапшот после бюджетного среза начинается не с r1 — валиден,
    # если id последовательны
    receipts = extract_tool_receipts([_stamped(i) for i in range(1, 6)])
    tail = [dict(r) for r in receipts[2:]]  # r3, r4, r5
    ai = AIMessage(content="x")
    ai.additional_kwargs = {TOOL_RECEIPT_LEDGER_KEY: tail}
    snapshot = extract_citing_turn_receipts([ai])
    assert [r["id"] for r in snapshot] == ["r3", "r4", "r5"]


def test_citing_snapshot_empty_list_is_valid_zero():
    ai = AIMessage(content="x")
    ai.additional_kwargs = {TOOL_RECEIPT_LEDGER_KEY: []}
    assert extract_citing_turn_receipts([ai]) == []


def test_citing_snapshot_uses_latest_stamped_ai():
    old = AIMessage(content="old")
    old.additional_kwargs = {
        TOOL_RECEIPT_LEDGER_KEY: [dict(r) for r in extract_tool_receipts([_stamped(1)])]
    }
    unstamped = AIMessage(content="no ledger")
    assert extract_citing_turn_receipts([old, unstamped]) is not None


def test_citation_anchor_allows_dots_and_dashes():
    assert parse_citations("[r1 my-tool.v2]") == [("r1", "my-tool.v2")]


def test_verify_r0_is_unknown_not_crash():
    verdict = verify_receipt_citations("done [r0]", extract_tool_receipts([_stamped(1)]))
    assert verdict["unknown"] == ["r0"]


# -- steps: дедуп через компакцию ---------------------------------------------


def test_compaction_survivors_not_recaptured():
    captured, seen = [], set()
    survivors = [AIMessage(content="keep", id="keep-1"), AIMessage(content="x", id="x-1")]
    cursor, _ = capture_new_step_messages(
        [*survivors, AIMessage(content="drop", id="d-1")], captured, seen, 0, task_id="t"
    )
    assert cursor == 3
    # компакция: выживший keep-1 + новое сообщение; сброс курсора не должен
    # продублировать keep-1
    compacted = [survivors[0], AIMessage(content="new", id="n-1")]
    _, new = capture_new_step_messages(compacted, captured, seen, cursor, task_id="t")
    assert [s["text"] for s in new] == ["new"]


def test_args_preview_truncation_flag():
    captured, seen = [], set()
    big_args = {"payload": "z" * 5000}
    msg = AIMessage(
        content="",
        id="a1",
        tool_calls=[{"name": "t", "args": big_args, "id": "c", "type": "tool_call"}],
    )
    capture_new_step_messages([msg], captured, seen, 0, task_id="t")
    call = captured[0]["tool_calls"][0]
    assert call["args_truncated"] and len(call["args"]) <= 2000


# -- middleware: анти-подделка и адресная штамповка ---------------------------


def _tool_request(call_id: str = "c1"):
    return SimpleNamespace(tool_call={"id": call_id, "name": "sandbox_run", "args": {}})


def test_stamp_overwrites_forged_receipt():
    mw = ToolReceiptMiddleware()
    forged = ToolMessage(content="out", tool_call_id="c1")
    forged.additional_kwargs = {TOOL_RECEIPT_KEY: {"tool_name": "forged", "status": "success"}}
    result = mw.wrap_tool_call(_tool_request(), lambda req: forged)
    receipt = result.additional_kwargs[TOOL_RECEIPT_KEY]
    assert receipt["tool_name"] == "sandbox_run"  # подделка перезаписана рантаймом


def test_stamp_command_only_matching_tool_call():
    from langgraph.types import Command

    mw = ToolReceiptMiddleware()
    mine = ToolMessage(content="a", tool_call_id="c1")
    other = ToolMessage(content="b", tool_call_id="other")
    command = Command(update={"messages": [mine, other]})
    mw.wrap_tool_call(_tool_request("c1"), lambda req: command)
    assert TOOL_RECEIPT_KEY in mine.additional_kwargs
    assert TOOL_RECEIPT_KEY not in (other.additional_kwargs or {})


def test_stamp_failure_never_blocks_tool_result():
    mw = ToolReceiptMiddleware()
    # tool_call без .get — make_tool_receipt упадёт, результат обязан вернуться
    bad_request = SimpleNamespace(tool_call=None)
    msg = ToolMessage(content="out", tool_call_id="c1")
    result = mw.wrap_tool_call(bad_request, lambda req: msg)
    assert result is msg


def test_inject_ledger_noop_without_receipts():
    mw = ToolReceiptMiddleware()
    request = MagicMock()
    request.messages = [SystemMessage(content="s"), HumanMessage(content="h")]
    new_request, snapshot = mw._inject_ledger(request)
    assert new_request is request and snapshot == []
    request.override.assert_not_called()


def test_inject_ledger_after_leading_system():
    mw = ToolReceiptMiddleware()
    request = MagicMock()
    request.messages = [SystemMessage(content="s"), HumanMessage(content="h"), _stamped(1)]
    mw._inject_ledger(request)
    (kwargs) = request.override.call_args.kwargs
    injected = kwargs["messages"]
    assert isinstance(injected[0], SystemMessage)  # system остаётся первым
    assert isinstance(injected[1], HumanMessage)
    assert "Tool receipts" in injected[1].content  # леджер сразу после system


# -- executor: сборка сообщений и урожай --------------------------------------


def test_build_messages_channel_split():
    messages = _build_messages(GENERAL_PURPOSE, "do the task", ["criterion-A", "  ", 42])
    assert len(messages) == 2
    system, human = messages
    assert isinstance(system, SystemMessage) and isinstance(human, HumanMessage)
    # значения критериев ТОЛЬКО в human; в system — только указатель
    assert "criterion-A" in human.content
    assert "criterion-A" not in system.content
    assert "acceptance_criteria" in system.content
    assert "report_contract" in system.content


def test_build_messages_without_criteria_has_no_pointer():
    system, _human = _build_messages(GENERAL_PURPOSE, "task", None)
    assert "acceptance_criteria" not in system.content


def test_extract_final_result_empty_ai_is_sentinel():
    state = {"messages": [AIMessage(content="")]}
    assert _extract_final_result(state) == "No response generated"
    assert _extract_final_result(None) == "No response generated"


def test_harvest_none_vs_empty():
    harvest = SubagentExecutor._harvest
    # нет состояния → None (вердикта не будет)
    assert harvest(None) is None
    # состояние без квитанций и снапшота → [] (честный ноль вызовов)
    assert harvest({"messages": [AIMessage(content="x")]}) == []
    # квитанции есть, снапшот битый → None (fail-closed)
    broken_ai = AIMessage(content="x")
    broken_ai.additional_kwargs = {TOOL_RECEIPT_LEDGER_KEY: "junk"}
    assert harvest({"messages": [_stamped(1), broken_ai]}) is None


def test_executor_generic_failure_captures_error():
    async def main():
        model = MagicMock()
        executor = SubagentExecutor(GENERAL_PURPOSE, model, [])
        boom = RuntimeError("model exploded")

        class _FailingAgent:
            def astream(self, *a, **k):
                raise boom

        # подменяем сборку графа моком
        import core.agents.factory as factory_module

        original = factory_module.build_agent
        factory_module.build_agent = lambda *a, **k: _FailingAgent()
        try:
            result = await executor.arun("task", task_id="t1")
        finally:
            factory_module.build_agent = original
        assert result.status is SubagentStatus.FAILED
        assert "model exploded" in result.error

    asyncio.run(main())


def test_executor_cancel_does_not_terminalize():
    async def main():
        model = MagicMock()
        executor = SubagentExecutor(GENERAL_PURPOSE, model, [])
        started = asyncio.Event()

        class _HangingAgent:
            async def astream(self, *a, **k):
                started.set()
                await asyncio.Event().wait()
                yield  # pragma: no cover

        import core.agents.factory as factory_module

        original = factory_module.build_agent
        factory_module.build_agent = lambda *a, **k: _HangingAgent()
        try:
            task = asyncio.create_task(executor.arun("task", task_id="t1"))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            factory_module.build_agent = original

    asyncio.run(main())


# -- sandbox-тулы: усечение и ошибки ------------------------------------------


def test_sandbox_tools_clip_and_error_text():
    async def main():
        from core.ports import SandboxCommandError

        class HugeSandbox:
            repo_dir = "/repo"

            async def run(self, command, *, timeout_seconds=None):
                if command.startswith("fail"):
                    raise SandboxCommandError(command, 2, "stderr text")
                return "y" * (SANDBOX_OUTPUT_MAX_CHARS + 100)

            async def close(self):
                pass

        run_tool, _read_tool = build_sandbox_tools(HugeSandbox())
        out = await run_tool.ainvoke({"command": "big"})
        assert len(out) <= SANDBOX_OUTPUT_MAX_CHARS + 20
        assert out.endswith("[truncated]")
        err = await run_tool.ainvoke({"command": "fail now"})
        assert err.startswith("exit 2:") and "stderr text" in err

        # read_file квотирует путь с пробелом — команда не ломается
        class EchoSandbox(HugeSandbox):
            async def run(self, command, *, timeout_seconds=None):
                return command

        _, read2 = build_sandbox_tools(EchoSandbox())
        cmd = await read2.ainvoke({"path": "/repo/my file.py"})
        assert "'/repo/my file.py'" in cmd

    asyncio.run(main())


def test_capacity_slot_released_on_exception():
    async def main():
        from core.subagents.capacity import SubagentCapacity

        cap = SubagentCapacity(max_running=1, max_queued=0, queue_timeout_seconds=1)
        with pytest.raises(RuntimeError):
            async with cap.slot():
                raise RuntimeError("boom")
        # слот освобождён — следующий заход не ждёт
        async with cap.slot():
            pass

    asyncio.run(main())


def test_limit_zero_budget_keeps_plain_tools_no_stop_note():
    from core.middleware.subagent_limit import SubagentLimitMiddleware

    mw = SubagentLimitMiddleware(max_concurrent=3, max_total_per_run=0)
    message = AIMessage(
        content="thinking",
        id="ai-1",
        tool_calls=[
            {"name": "task", "args": {}, "id": "tc1", "type": "tool_call"},
            {"name": "sandbox_run", "args": {}, "id": "oc1", "type": "tool_call"},
        ],
        response_metadata={"finish_reason": "tool_calls"},
    )
    update = mw.after_model({"messages": [message]}, None)
    clone = update["messages"][0]
    assert [c["name"] for c in clone.tool_calls] == ["sandbox_run"]
    # остались обычные вызовы: finish_reason не трогаем, заметку не добавляем
    assert clone.response_metadata["finish_reason"] == "tool_calls"
    assert "SUBAGENT LIMIT" not in clone.content


def test_child_config_never_carries_checkpoint_coordinates():
    """Пин линиджа: configurable-ключи в конфиге ребёнка на langgraph>=1.2.6
    стартуют новый корневой линидж/утаскивают фреймы ребёнка в родительский
    стрим. Ребёнок обязан получать координаты только амбиентно (и с
    checkpointer=False им некуда персиститься)."""

    async def main():
        captured_config = {}

        class _SpyAgent:
            async def astream(self, state, config=None, stream_mode=None):
                captured_config.update(config or {})
                return
                yield  # pragma: no cover

        import core.agents.factory as factory_module

        original = factory_module.build_agent
        captured_kwargs = {}

        def spy_build(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return _SpyAgent()

        factory_module.build_agent = spy_build
        try:
            executor = SubagentExecutor(GENERAL_PURPOSE, MagicMock(), [])
            await executor.arun("task", task_id="t1")
        finally:
            factory_module.build_agent = original

        assert "configurable" not in captured_config
        assert set(captured_config) == {"recursion_limit", "callbacks", "tags"}
        assert captured_kwargs["checkpointer"] is False

    asyncio.run(main())
