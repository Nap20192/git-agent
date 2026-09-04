"""ShieldedPostgresSaver: отмена хода не обрывает операцию чекпоинта (соединение
возвращается в пул), но сама отмена до вызывающего доходит."""

import asyncio

import pytest

from infra.db.checkpointer import ShieldedPostgresSaver


class _Slow:
    """Подмена базовых операций: медленная операция с фиксацией завершения."""

    def __init__(self) -> None:
        self.finished: list[str] = []

    async def op(self, name: str) -> str:
        await asyncio.sleep(0.05)
        self.finished.append(name)
        return name


def test_cancel_lets_checkpoint_op_finish(monkeypatch):
    slow = _Slow()
    saver = ShieldedPostgresSaver.__new__(ShieldedPostgresSaver)  # без соединения
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    monkeypatch.setattr(AsyncPostgresSaver, "aput", lambda self, *a: slow.op("aput"))
    monkeypatch.setattr(AsyncPostgresSaver, "aget_tuple", lambda self, c: slow.op("aget_tuple"))

    async def run():
        task = asyncio.create_task(saver.aput({}, {}, {}, {}))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.1)  # операция под shield доживает до конца
        assert slow.finished == ["aput"]
        assert await saver.aget_tuple({}) == "aget_tuple"

    asyncio.run(run())
