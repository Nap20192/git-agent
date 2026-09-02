"""Runtime.chat: тред-континуация поверх memory-рантайма (без durable-admission)."""

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from core.runtime import MemoryRunStore, MemoryStreamBridge, Runtime
from core.runtime.profile import GraphProfile

CLAIM = dict(
    repository_id=1,
    commit_sha="abc",
    llm_api_base="http://x",
    llm_api_key="k",
    llm_model="m",
    owner_worker_id="w1",
    lease_seconds=30,
    grace_seconds=10,
)


class _FakeSandbox:
    repo_dir = "/repo"
    id = "sbx-1"

    async def run(self, command, *, timeout_seconds=None):
        return ""

    async def close(self):
        pass


class _ChatGraph:
    async def astream(self, graph_input, config=None, stream_mode=None):
        yield "updates", {"lead": {"messages": [AIMessage(content="thinking")]}}

    async def aget_state(self, config):
        return SimpleNamespace(values={"messages": [AIMessage(content="here is the answer")]})


def _runtime(store, bridge, provisioned):
    async def fake_provision(run_id, name, *, is_resume=False):
        provisioned.append((run_id, is_resume))
        return _FakeSandbox(), True

    return Runtime(
        store=store,
        bridge=bridge,
        profile=GraphProfile(
            build=lambda sb, m, checkpointer=None, limits=None: _ChatGraph(),
            make_input=lambda *a, **k: {},
            extract_report=lambda v: None,
            stream_modes=["updates"],
        ),
        make_model=lambda **kw: object(),
        provision_sandbox=fake_provision,
        get_or_create_repository=lambda url: {"id": 1},
    )


def test_chat_streams_persists_and_keeps_status():
    async def main():
        store, bridge = MemoryRunStore(), MemoryStreamBridge()
        row, _ = await store.claim(**CLAIM)
        run_id = row["id"]
        await store.start_run(run_id, owner_worker_id="w1")
        await store.finalize_if_not_cancelled(run_id, owner_worker_id="w1", report={"ok": 1})

        provisioned: list = []
        rt = _runtime(store, bridge, provisioned)

        chunks = [(mode, data) async for mode, data in rt.chat(run_id, "why?")]
        assert chunks and chunks[0][0] == "updates"
        assert provisioned == [(run_id, True)]

        history = await rt.chat_history(run_id)
        assert [t["role"] for t in history] == ["user", "agent"]
        assert history[0]["text"] == "why?"
        assert history[1]["text"] == "here is the answer"

        assert (await store.get(run_id))["status"] == "succeeded"

    asyncio.run(main())


def test_chat_serializes_per_run():
    async def main():
        store, bridge = MemoryRunStore(), MemoryStreamBridge()
        row, _ = await store.claim(**CLAIM)
        run_id = row["id"]
        rt = _runtime(store, bridge, [])
        await asyncio.gather(
            _drain(rt.chat(run_id, "a")),
            _drain(rt.chat(run_id, "b")),
        )
        roles = [t["role"] for t in await rt.chat_history(run_id)]
        assert roles == ["user", "agent", "user", "agent"]

    asyncio.run(main())


def test_gateway_chat_rejects_pipeline_and_lists_history(monkeypatch):
    from fastapi.testclient import TestClient

    import infra.db.postgres
    from infra.server.app import create_app

    store, bridge = MemoryRunStore(), MemoryStreamBridge()
    row, _ = asyncio.run(store.claim(**CLAIM))
    rid = row["id"]
    rt = _runtime(store, bridge, [])
    client = TestClient(create_app(runtime=rt))

    def fake_get(run_id):
        r = asyncio.run(store.get(run_id))
        return {**r, "repo_url": "x", "sandbox_name": "git"} if r else None

    monkeypatch.setattr(infra.db.postgres, "get_run_with_repo", fake_get)

    resp = client.post(f"/api/runs/{rid}/chat", json={"message": "hi"})
    assert resp.status_code == 422 and "not_agent" in resp.text

    hist = client.get(f"/api/runs/{rid}/chat")
    assert hist.status_code == 200 and hist.json() == {"turns": []}


async def _drain(agen):
    async for _ in agen:
        pass


if __name__ == "__main__":
    test_chat_streams_persists_and_keeps_status()
    test_chat_serializes_per_run()
    print("ok")
