"""Лимиты делегации: срез task-вызовов, гигиена клона, бюджет на ран."""

from langchain_core.messages import AIMessage, ToolMessage

from core.middleware.subagent_limit import (
    SubagentLimitMiddleware,
    clone_ai_message_with_tool_calls,
)
from core.subagents.contract import SUBAGENT_STATUS_KEY


def _task_call(i: int) -> dict:
    return {"name": "task", "args": {"prompt": f"p{i}"}, "id": f"tc{i}", "type": "tool_call"}


def _other_call(i: int) -> dict:
    return {"name": "sandbox_run", "args": {}, "id": f"oc{i}", "type": "tool_call"}


def _ai(calls: list[dict]) -> AIMessage:
    return AIMessage(
        content="",
        id="ai-1",
        tool_calls=calls,
        additional_kwargs={
            "tool_calls": [{"id": c["id"], "type": "function"} for c in calls],
            "function_call": {"name": "legacy"},
        },
        response_metadata={"finish_reason": "tool_calls"},
    )


def test_concurrent_strip_keeps_non_task_calls():
    mw = SubagentLimitMiddleware(max_concurrent=2, max_total_per_run=10)
    state = {"messages": [_ai([_task_call(1), _task_call(2), _task_call(3), _other_call(1)])]}
    update = mw.after_model(state, None)
    clone = update["messages"][0]
    names_ids = [(c["name"], c["id"]) for c in clone.tool_calls]
    assert names_ids == [("task", "tc1"), ("task", "tc2"), ("sandbox_run", "oc1")]
    assert clone.id == "ai-1"  # тот же id: замена, не дописывание
    raw_ids = [c["id"] for c in clone.additional_kwargs["tool_calls"]]
    assert raw_ids == ["tc1", "tc2", "oc1"]  # provider-raw тоже отфильтрован


def test_total_budget_counts_prior_delegations():
    mw = SubagentLimitMiddleware(max_concurrent=3, max_total_per_run=2)
    prior = [
        ToolMessage(
            content="done",
            tool_call_id=f"old{i}",
            additional_kwargs={SUBAGENT_STATUS_KEY: "completed"},
        )
        for i in range(2)
    ]
    state = {"messages": [*prior, _ai([_task_call(1)])]}
    update = mw.after_model(state, None)
    clone = update["messages"][0]
    assert clone.tool_calls == []  # бюджет исчерпан
    assert "SUBAGENT LIMIT REACHED" in clone.content
    assert clone.response_metadata["finish_reason"] == "stop"
    assert "function_call" not in clone.additional_kwargs
    assert "tool_calls" not in clone.additional_kwargs


def test_within_limits_is_noop():
    mw = SubagentLimitMiddleware()
    state = {"messages": [_ai([_task_call(1)])]}
    assert mw.after_model(state, None) is None
    assert mw.after_model({"messages": [AIMessage(content="text", id="x")]}, None) is None


def test_clone_hygiene_all_stripped():
    message = _ai([_task_call(1)])
    clone = clone_ai_message_with_tool_calls(message, set())
    assert clone.tool_calls == []
    assert clone.response_metadata["finish_reason"] == "stop"
    assert "function_call" not in clone.additional_kwargs
