"""Контракт статусов/результата: пины значений и терминализации."""

import pytest

from core.agents.subagents.contract import (
    SUBAGENT_STATUS_VALUES,
    SUBAGENT_STOP_REASON_VALUES,
    SubagentResult,
    SubagentStatus,
    format_subagent_result_message,
    make_subagent_additional_kwargs,
    normalize_token_usage,
    read_subagent_result_metadata,
)


def test_status_and_stop_reason_values_pinned():
    assert SUBAGENT_STATUS_VALUES == ("completed", "failed", "cancelled", "timed_out")
    assert SUBAGENT_STOP_REASON_VALUES == ("token_capped", "turn_capped", "loop_capped")


def test_terminal_once_loser_writes_nothing():
    r = SubagentResult(task_id="t1")
    assert r.try_set_terminal(SubagentStatus.COMPLETED, result="done")
    # поздний писатель (таймаут) проигрывает целиком
    assert not r.try_set_terminal(SubagentStatus.TIMED_OUT, error="late")
    assert r.status is SubagentStatus.COMPLETED
    assert r.result == "done" and r.error is None


def test_try_set_terminal_rejects_non_terminal():
    r = SubagentResult(task_id="t1")
    with pytest.raises(ValueError):
        r.try_set_terminal(SubagentStatus.RUNNING)


def test_progress_writers_noop_after_terminal():
    r = SubagentResult(task_id="t1")
    r.try_set_terminal(SubagentStatus.FAILED, error="x")
    r.update_token_usage_records([{"total_tokens": 5}])
    r.update_tool_receipts([{"id": "r1"}])
    assert r.token_usage_records == [] and r.tool_receipts is None


def test_capped_completed_carries_result_like_clean_success():
    kwargs = make_subagent_additional_kwargs(
        SubagentStatus.COMPLETED, result="partial work", stop_reason="turn_capped"
    )
    meta = read_subagent_result_metadata(kwargs)
    assert meta["status"] == "completed" and meta["stop_reason"] == "turn_capped"
    assert meta["result_brief"] == "partial work"
    assert len(meta["result_sha256"]) == 64
    text = format_subagent_result_message(
        SubagentStatus.COMPLETED, result="partial work", stop_reason="turn_capped"
    )
    assert "capped: turn budget" in text


def test_producer_validates_loudly():
    with pytest.raises(ValueError):
        make_subagent_additional_kwargs(SubagentStatus.RUNNING)
    with pytest.raises(ValueError):
        make_subagent_additional_kwargs(SubagentStatus.FAILED, stop_reason="martian")


def test_reader_trusts_nothing():
    assert read_subagent_result_metadata(None) is None
    assert read_subagent_result_metadata({"subagent_status": "martian"}) is None
    meta = read_subagent_result_metadata(
        {
            "subagent_status": "completed",
            "subagent_result_sha256": "NOT-A-HASH",
            "subagent_stop_reason": "martian",
        }
    )
    assert "result_sha256" not in meta and "stop_reason" not in meta


def test_normalize_token_usage_bool_trap():
    assert (
        normalize_token_usage({"input_tokens": True, "output_tokens": 1, "total_tokens": 2}) is None
    )
    assert (
        normalize_token_usage({"input_tokens": 1, "output_tokens": 1, "total_tokens": -2}) is None
    )
    assert normalize_token_usage({"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}) == {
        "input_tokens": 1,
        "output_tokens": 2,
        "total_tokens": 3,
    }
