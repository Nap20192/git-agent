"""Activity-кадры хода (тикет 012) герметично: коллектор, фид, сервис, SSE."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from core.runner.activity import ActivityCollector, ActivityFeed
from infra.server.runner_api import install_api
from tests.unit.test_runner import WIRE, FakeExecutor, MemStore, make_service, parse_event, seed


def _strip_ts(frames):
    return [{k: v for k, v in f.items() if k != "ts"} for f in frames]


def test_collector_task_lifecycle():
    c = ActivityCollector()
    started = c.frames("custom", {"type": "task_started", "task_id": "t1", "description": "auth"})
    assert _strip_ts(started) == [
        {"kind": "task_started", "taskId": "t1", "description": "auth", "status": "queued"}
    ]
    # первый прогресс — queued→working, дальнейшие шаги кадров не плодят
    working = c.frames("custom", {"type": "task_running", "task_id": "t1", "step": 1})
    assert _strip_ts(working) == [{"kind": "task_started", "taskId": "t1", "status": "working"}]
    assert c.frames("custom", {"type": "task_running", "task_id": "t1", "step": 2}) == []
    done = c.frames(
        "custom", {"type": "task_completed", "task_id": "t1", "findings": [{"a": 1}, {"b": 2}]}
    )
    assert _strip_ts(done) == [
        {"kind": "task_finished", "taskId": "t1", "status": "done", "findingsCount": 2}
    ]


def test_collector_task_failures_map_status():
    c = ActivityCollector()
    timeout = c.frames("custom", {"type": "task_timed_out", "task_id": "t1", "error": "600s"})
    assert _strip_ts(timeout) == [
        {"kind": "task_failed", "taskId": "t1", "status": "timeout", "description": "600s"}
    ]
    failed = c.frames("custom", {"type": "task_failed", "task_id": "t2", "error": "boom"})
    assert failed[0]["status"] == "failed"


def test_collector_updates_nodes_findings_and_report():
    c = ActivityCollector()
    frames = c.frames(
        "updates",
        {
            "lead": {
                "messages": [
                    {
                        "type": "ai",
                        "tool_calls": [{"name": "report_finding"}, {"name": "sandbox_run"}],
                    },
                    {"type": "tool", "name": "task", "tool_call_id": "t1", "content": "самоотчёт"},
                ]
            }
        },
    )
    assert _strip_ts(frames) == [
        {"kind": "tool_call", "description": "report_finding()"},
        {"kind": "tool_call", "description": "sandbox_run()"},
        {"kind": "task_report", "taskId": "t1", "description": "самоотчёт"},
        {"kind": "node", "description": "lead", "status": "done", "findingsCount": 1},
    ]
    assert c.run_finished()["findingsCount"] == 1


def test_collector_lead_work_log():
    """Лид: мысль → text, вызов тула с аргументами → tool_call, ответ тула → tool_result
    (превью усечено); ToolMessage task-тула — task_report, не tool_result."""
    c = ActivityCollector()
    frames = c.frames(
        "updates",
        {
            "model": {
                "messages": [
                    {
                        "type": "ai",
                        "content": "Let me map the entry points.",
                        "tool_calls": [
                            {"name": "grep_code", "args": {"pattern": "app.get(", "path": "src"}}
                        ],
                    }
                ]
            },
            "tools": {"messages": [{"type": "tool", "name": "grep_code", "content": "x" * 5000}]},
        },
    )
    kinds = [(f["kind"], f.get("taskId")) for f in frames]
    assert kinds == [
        ("text", None),
        ("tool_call", None),
        ("node", None),
        ("tool_result", None),
        ("node", None),
    ]
    assert frames[0]["description"] == "Let me map the entry points."
    assert frames[1]["description"] == 'grep_code(pattern="app.get(", path="src")'
    assert frames[3]["description"].startswith("grep_code: xxx") and frames[3][
        "description"
    ].endswith("…")
    assert len(frames[3]["description"]) < 900


def test_collector_subagent_work_log_from_steps():
    """Шаги Сабагента (task_running + build_subagent_step) → work log с taskId; первый шаг
    ещё и переводит queued → working."""
    c = ActivityCollector()
    c.frames("custom", {"type": "task_started", "task_id": "t1", "description": "deps"})
    ai = {
        "type": "task_running",
        "task_id": "t1",
        "kind": "ai",
        "text": "Checking lockfile",
        "tool_calls": [{"name": "read_file", "args": '{"path": "package-lock.json"}'}],
    }
    frames = _strip_ts(c.frames("custom", ai))
    assert frames == [
        {"kind": "task_started", "taskId": "t1", "status": "working"},
        {"kind": "text", "taskId": "t1", "description": "Checking lockfile"},
        {"kind": "tool_call", "taskId": "t1", "description": 'read_file(path="package-lock.json")'},
    ]
    tool = {
        "type": "task_running",
        "task_id": "t1",
        "kind": "tool",
        "tool_name": "read_file",
        "text": "1\t{",
    }
    assert _strip_ts(c.frames("custom", tool)) == [
        {"kind": "tool_result", "taskId": "t1", "description": "read_file: 1\t{"}
    ]
    assert (
        c.frames("custom", {"type": "task_running", "task_id": "t1", "kind": "ai", "text": ""})
        == []
    )


def test_collector_ignores_garbage():
    c = ActivityCollector()
    assert c.frames("custom", {"note": "думаю"}) == []
    assert c.frames("messages", {"type": "task_started", "task_id": "x"}) == []
    assert c.frames("updates", "не dict") == []


def test_feed_live_stream_and_replay():
    async def run():
        feed = ActivityFeed()
        persisted = []

        async def persist(seq, frame):
            persisted.append((seq, frame["kind"]))

        turn = feed.begin(3, 7, persist)
        await turn.emit({"kind": "run_started"})

        collected = []

        async def subscriber():
            async for frame in turn.stream():
                collected.append(frame["kind"])

        task = asyncio.ensure_future(subscriber())
        await asyncio.sleep(0)  # подписка до следующих кадров
        await turn.emit({"kind": "task_started"})
        turn.close()
        await asyncio.wait_for(task, 1)
        assert collected == ["run_started", "task_started"]  # реплей буфера + live
        assert persisted == [(1, "run_started"), (2, "task_started")]
        assert feed.live(3) is None  # завершённый ход не live

        # подписка после завершения — только реплей буфера
        late = [f["kind"] async for f in turn.stream()]
        assert late == ["run_started", "task_started"]

    asyncio.run(run())


def test_handle_event_records_activity():
    async def run():
        store = MemStore()
        seed(store)
        executor = FakeExecutor()
        executor.chunks = [
            ("custom", {"type": "task_started", "task_id": "t1", "description": "auth"}),
            ("custom", {"type": "task_completed", "task_id": "t1", "findings": []}),
        ]
        service = make_service(store, executor=executor)
        await service.start()
        assert await service.handle_event(parse_event(WIRE)) == "processed"
        kinds = [frame["kind"] for (_, eid, _, frame) in store.activity]
        assert kinds == ["run_started", "task_started", "task_finished", "run_finished"]
        assert {eid for (_, eid, _, _) in store.activity} == {7}
        # завершённый ход отдаётся реплеем из стора
        replay = [f["kind"] async for f in service.activity(3, event_id=7)]
        assert replay == kinds
        latest = [f["kind"] async for f in service.activity(3)]
        assert latest == kinds

    asyncio.run(run())


def test_failed_event_records_run_failed():
    async def run():
        store = MemStore()
        seed(store)
        executor = FakeExecutor(error=RuntimeError("boom"))
        service = make_service(store, executor=executor)
        await service.start()
        with pytest.raises(RuntimeError):
            await service.handle_event(parse_event(WIRE))
        kinds = [frame["kind"] for (_, _, _, frame) in store.activity]
        assert kinds == ["run_started", "run_failed"]
        assert store.activity[-1][3]["description"] == "RuntimeError: boom"

    asyncio.run(run())


def test_activity_sse_replay_and_done():
    """GET /instances/{id}/activity — кадры ActivityEvent + терминальный done."""
    app = FastAPI()
    install_api(app)

    class Service:
        async def activity(self, instance_id, *, event_id=None):
            assert (instance_id, event_id) == (3, 7)
            yield {"kind": "run_started", "ts": "2026-01-01T00:00:00Z"}
            yield {"kind": "run_finished", "findingsCount": 0, "ts": "2026-01-01T00:01:00Z"}

    app.state.service = Service()
    client = TestClient(app)
    with client.stream("GET", "/instances/3/activity?eventId=7") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    frames = [json.loads(line[len("data: ") :]) for line in body.splitlines() if line]
    assert [f["kind"] for f in frames] == ["run_started", "run_finished", "done"]
    assert frames[1]["findingsCount"] == 0
