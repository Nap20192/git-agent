"""Захват шагов: мульти-tool супер-шаг, сброс курсора при компакции, дедуп."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from core.subagents.steps import capture_new_step_messages


def _run(messages, captured, seen, cursor):
    return capture_new_step_messages(messages, captured, seen, cursor, task_id="t")


def test_multi_toolmessage_super_step():
    captured, seen = [], set()
    messages = [
        HumanMessage(content="go", id="h1"),
        AIMessage(
            content="",
            id="a1",
            tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}],
        ),
        ToolMessage(content="r1", tool_call_id="c1", id="t1"),
        ToolMessage(content="r2", tool_call_id="c2", id="t2"),
    ]
    cursor, new = _run(messages, captured, seen, 0)
    assert cursor == 4
    # human не захвачен; оба ToolMessage взяты, не только messages[-1]
    assert [s["kind"] for s in new] == ["ai", "tool", "tool"]


def test_no_growth_rechecks_tail_and_dedups():
    captured, seen = [], set()
    messages = [AIMessage(content="a", id="a1")]
    cursor, new = _run(messages, captured, seen, 0)
    assert len(new) == 1
    # тот же список, та же длина: id уже виден — дубля нет
    cursor, new = _run(messages, captured, seen, cursor)
    assert new == []
    # in-place замена последнего (новый id) — захвачена
    messages[-1] = AIMessage(content="a2", id="a2")
    cursor, new = _run(messages, captured, seen, cursor)
    assert len(new) == 1 and new[0]["text"] == "a2"


def test_compaction_resets_cursor():
    captured, seen = [], set()
    messages = [AIMessage(content=str(i), id=f"a{i}") for i in range(5)]
    cursor, _ = _run(messages, captured, seen, 0)
    assert cursor == 5
    # компакция сжала историю и добавила новое сообщение
    compacted = [AIMessage(content="summary", id="s1"), AIMessage(content="new", id="a9")]
    cursor, new = _run(compacted, captured, seen, cursor)
    assert cursor == 2
    assert [s["text"] for s in new] == ["summary", "new"]  # хвост не потерян


def test_none_content_is_empty_not_none_string():
    from core.subagents.steps import _content_to_text

    assert _content_to_text(None) == ""  # не строка "None"
