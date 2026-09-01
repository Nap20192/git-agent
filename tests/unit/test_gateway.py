"""Тесты HTTP-gateway: wire-формат, redaction, граф, роуты поверх memory-рантайма."""

import asyncio
import json
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from core.runtime import MemoryRunStore, MemoryStreamBridge, Runtime
from core.runtime.profile import GraphProfile
from server import wire
from server.app import create_app
from server.graphview import derive_graph, node_spec, pipeline_topology

# ── wire: чистые функции ──


def test_mask_key_never_leaks():
    assert wire.mask_key("sk-secret-abcd") == "…abcd"
    assert "secret" not in wire.mask_key("sk-secret-abcd")
    assert wire.mask_key(None) == ""
    assert wire.mask_key("ab") == "…"


def test_repo_slug():
    assert wire.repo_slug("https://github.com/org/repo.git") == "org/repo"
    assert wire.repo_slug("git@github.com:org/repo.git") == "org/repo"
    assert wire.repo_slug("/tmp/myrepo") == "tmp/myrepo"


def _row(**over):
    base = {
        "id": 7,
        "repository_id": 3,
        "repo_url": "https://github.com/org/repo",
        "commit_sha": "abc123",
        "status": "succeeded",
        "error": None,
        "stop_reason": None,
        "cancel_requested_at": None,
        "attempt": 1,
        "llm_api_base": "https://api.deepseek.com",
        "llm_api_key": "sk-verysecretkey",
        "llm_model": "deepseek-chat",
        "sandbox_name": "git",
        "report": {"repo_url": "x"},
        "started_at": datetime(2026, 1, 1, tzinfo=UTC),
        "finished_at": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
    }
    return {**base, **over}


def test_run_to_wire_redacts_key():
    payload = json.dumps(wire.run_to_wire(_row()))
    assert "verysecretkey" not in payload  # инвариант redaction
    parsed = json.loads(payload)
    assert parsed["connection"]["keyMasked"] == "…tkey"
    assert parsed["id"] == "7" and parsed["repo"] == "org/repo"
    assert parsed["hasReport"] is True
    assert parsed["metrics"]["elapsedSec"] == 60


def test_event_to_wire_updates_and_task():
    updates = wire.event_to_wire(1, "updates", {"data": {"scan": {"files": 1}}})
    assert updates["type"] == "node_update"
    assert updates["data"] == {"kind": "node_status", "node": "scan", "status": "completed"}

    started = wire.event_to_wire(
        2,
        "custom",
        {"data": {"type": "task_started", "task_id": "t1", "subagent_type": "general-purpose"}},
    )
    assert started["type"] == "task_started" and started["data"]["taskId"] == "t1"

    done = wire.event_to_wire(
        3,
        "custom",
        {
            "data": {
                "type": "task_completed",
                "task_id": "t1",
                "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
            }
        },
    )
    assert done["data"]["status"] == "completed"
    assert done["data"]["usage"]["totalTokens"] == 7


# ── graphview ──


def _event(kind, data):
    return {"kind": kind, "payload": {"data": data}}


def test_pipeline_graph_statuses():
    ids, _edges = pipeline_topology()
    assert ids == ["scan", "parse", "report"]  # из LangGraph get_graph
    row = _row(status="running")
    graph = derive_graph(row, [_event("updates", {"scan": {}})])
    by_id = {n["id"]: n["status"] for n in graph["nodes"]}
    assert by_id == {"scan": "completed", "parse": "running", "report": "pending"}
    assert any(e["conditional"] for e in graph["edges"])


def test_pipeline_graph_error_node():
    row = _row(status="failed", error="parse: boom")
    graph = derive_graph(row, [_event("updates", {"scan": {}})])
    by_id = {n["id"]: n["status"] for n in graph["nodes"]}
    assert by_id["parse"] == "error"


def test_agent_graph_star():
    events = [
        _event(
            "custom",
            {
                "type": "task_started",
                "task_id": "t1",
                "subagent_type": "general-purpose",
                "description": "read docs",
            },
        ),
        _event("custom", {"type": "task_completed", "task_id": "t1", "usage": {"total_tokens": 9}}),
    ]
    graph = derive_graph(_row(status="succeeded"), events)
    assert {n["id"] for n in graph["nodes"]} == {"lead", "t1"}
    t1 = next(n for n in graph["nodes"] if n["id"] == "t1")
    assert t1["parentId"] == "lead" and t1["status"] == "completed"
    assert graph["edges"] == [{"from": "lead", "to": "t1", "conditional": False}]

    spec = node_spec(_row(), "t1", events)
    assert spec["delegation"]["status"] == "completed"
    lead = node_spec(_row(), "lead", events)
    assert any(t["name"] == "task" for t in lead["tools"])


# ── роуты поверх memory-рантайма ──


class _FakeState:
    def __init__(self, values):
        self.values = values


class _FakeGraph:
    async def astream(self, graph_input, config=None, stream_mode=None):
        yield "updates", {"scan": {"ok": 1}}

    async def aget_state(self, config):
        return _FakeState({"report": {"repo_url": "x", "commit": "abc"}})


class _FakeSandbox:
    repo_dir = "/repo"

    async def run(self, command, *, timeout_seconds=None):
        return ""

    async def close(self):
        pass


def _make_runtime(store, bridge):
    async def fake_repo(url):
        return {"id": 1, "url": url}

    async def fake_sandbox(name):
        return _FakeSandbox()

    return Runtime(
        store=store,
        bridge=bridge,
        profile=GraphProfile(
            build=lambda sb, m, checkpointer=None: _FakeGraph(),
            make_input=lambda repo_url, checkout_ref=None: {"repo_url": repo_url},
            extract_report=lambda values: (values or {}).get("report"),
        ),
        make_model=lambda **kw: object(),
        create_sandbox=fake_sandbox,
        get_or_create_repository=fake_repo,
    )


def test_gateway_routes_over_memory_runtime(monkeypatch):
    store, bridge = MemoryRunStore(), MemoryStreamBridge()
    runtime = _make_runtime(store, bridge)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    async def fake_sha(url):
        return "c" * 40

    import core.repo

    monkeypatch.setattr(core.repo, "resolve_commit_sha", fake_sha)

    def fake_get_run_with_repo(run_id):
        row = asyncio.run(store.get(run_id))
        if row is None:
            return None
        return {**row, "repo_url": "https://github.com/org/repo", "sandbox_name": "git"}

    def fake_list():
        rows = []
        rid = 1
        while (row := asyncio.run(store.get(rid))) is not None:
            rows.append({**row, "repo_url": "https://github.com/org/repo", "sandbox_name": "git"})
            rid += 1
        return rows

    import infra.postgres

    monkeypatch.setattr(infra.postgres, "get_run_with_repo", fake_get_run_with_repo)
    monkeypatch.setattr(infra.postgres, "list_runs_with_repo", fake_list)

    # submit → created; ключ не утёк в ответ
    resp = client.post(
        "/api/runs", json={"repoUrl": "https://github.com/org/repo", "apiKey": "sk-verysecret"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["disposition"] == "created"
    assert "sk-verysecret" not in resp.text

    run_id = body["run"]["id"]
    # воркер живёт в event loop TestClient — ждём терминала поллингом через API
    for _ in range(200):
        single = client.get(f"/api/runs/{run_id}").json()
        if single["status"] not in ("pending", "running"):
            break
        time.sleep(0.02)
    assert single["status"] == "succeeded"

    # идемпотентность через HTTP
    again = client.post(
        "/api/runs", json={"repoUrl": "https://github.com/org/repo", "apiKey": "sk-verysecret"}
    )
    assert again.json()["disposition"] == "already_succeeded"
    assert again.json()["run"]["id"] == run_id

    # список и одиночный ран
    assert client.get("/api/runs").json()["runs"][0]["id"] == run_id
    single = client.get(f"/api/runs/{run_id}").json()
    assert single["status"] == "succeeded"

    # отчёт в camelCase
    report = client.get(f"/api/runs/{run_id}/report").json()
    assert report["repoUrl"] == "x"

    # граф
    graph = client.get(f"/api/runs/{run_id}/graph").json()
    assert {n["id"] for n in graph["nodes"]} == {"scan", "parse", "report"}

    # SSE: реплей завершённого рана заканчивается терминальным status-событием
    with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
        lines = [ln for ln in stream.iter_lines() if ln.startswith("data: ")]
    events = [json.loads(ln.removeprefix("data: ")) for ln in lines]
    assert events[0]["type"] == "node_update"
    assert events[-1]["type"] == "status"
    assert events[-1]["data"]["status"] == "succeeded"

    # 404 с ApiError-формой
    missing = client.get("/api/runs/999")
    assert missing.status_code == 404
    assert missing.json()["detail"]["error"]["code"] == "not_found"
