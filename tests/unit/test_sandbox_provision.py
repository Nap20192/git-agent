"""provision_sandbox: create-vs-connect решение (без БД/SDK — на монкейпатчах)."""

import asyncio

import infra.sandbox.sandboxes as sb


class _Fake:
    def __init__(self, sid):
        self.id = sid


def _patch(monkeypatch, *, spec, alive=None, connect_raises=False):
    calls = {"created": 0, "connected": 0, "recorded": [], "dead": []}

    monkeypatch.setattr(sb, "get_sandbox_spec", lambda name: spec)
    monkeypatch.setattr(sb, "alive_instance_for_run", lambda run_id: alive)

    async def _create(name=sb.DEFAULT_SANDBOX):
        calls["created"] += 1
        return _Fake("new-sbx")

    async def _connect(external_id):
        if connect_raises:
            raise RuntimeError("dead endpoint")
        calls["connected"] += 1
        return _Fake(external_id)

    monkeypatch.setattr(sb, "create_sandbox_by_name", _create)
    monkeypatch.setattr(sb, "connect_sandbox", _connect)
    monkeypatch.setattr(sb, "record_instance", lambda *a: calls["recorded"].append(a))
    monkeypatch.setattr(sb, "mark_dead", lambda ext: calls["dead"].append(ext))
    return calls


OPEN = {"kind": "opensandbox", "image": "alpine/git:latest"}


def test_resume_reconnects_to_alive(monkeypatch):
    calls = _patch(monkeypatch, spec=OPEN, alive={"external_id": "live-1"})
    sandbox, reused = asyncio.run(sb.provision_sandbox(5, "git", is_resume=True))
    assert reused is True and sandbox.id == "live-1"
    assert calls["connected"] == 1 and calls["created"] == 0
    assert calls["recorded"] == []


def test_resume_dead_reconnect_falls_back_to_fresh(monkeypatch):
    calls = _patch(monkeypatch, spec=OPEN, alive={"external_id": "live-1"}, connect_raises=True)
    sandbox, reused = asyncio.run(sb.provision_sandbox(5, "git", is_resume=True))
    assert reused is False and sandbox.id == "new-sbx"
    assert calls["dead"] == ["live-1"]
    assert calls["created"] == 1 and len(calls["recorded"]) == 1


def test_fresh_run_creates_and_records(monkeypatch):
    calls = _patch(monkeypatch, spec=OPEN, alive=None)
    sandbox, reused = asyncio.run(sb.provision_sandbox(9, "git", is_resume=False))
    assert reused is False and sandbox.id == "new-sbx"
    assert calls["connected"] == 0 and calls["created"] == 1
    assert calls["recorded"] == [("new-sbx", "opensandbox", "alpine/git:latest", 9)]
