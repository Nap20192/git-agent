"""Admission: FIFO, ограниченная очередь, таймаут, отмена."""

import asyncio

import pytest

from core.agents.subagents.capacity import (
    SubagentCapacity,
    SubagentCapacityRejected,
    SubagentCapacityTimeout,
)


def test_fifo_order_and_bounded_queue():
    async def main():
        cap = SubagentCapacity(max_running=1, max_queued=2, queue_timeout_seconds=5)
        order: list[int] = []
        release = asyncio.Event()

        async def holder():
            async with cap.slot():
                await release.wait()

        async def waiter(i: int):
            async with cap.slot():
                order.append(i)

        h = asyncio.create_task(holder())
        await asyncio.sleep(0.01)
        w1 = asyncio.create_task(waiter(1))
        await asyncio.sleep(0.01)
        w2 = asyncio.create_task(waiter(2))
        await asyncio.sleep(0.01)
        # очередь полна (2) — третий отвергается сразу
        with pytest.raises(SubagentCapacityRejected):
            async with cap.slot():
                pass
        release.set()
        await asyncio.gather(h, w1, w2)
        assert order == [1, 2]  # FIFO

    asyncio.run(main())


def test_queue_timeout():
    async def main():
        cap = SubagentCapacity(max_running=1, max_queued=2, queue_timeout_seconds=0.05)
        release = asyncio.Event()

        async def holder():
            async with cap.slot():
                await release.wait()

        h = asyncio.create_task(holder())
        await asyncio.sleep(0.01)
        with pytest.raises(SubagentCapacityTimeout):
            async with cap.slot():
                pass
        release.set()
        await h

    asyncio.run(main())


def test_cancelled_waiter_reraises_and_leaks_no_slot():
    async def main():
        cap = SubagentCapacity(max_running=1, max_queued=2, queue_timeout_seconds=5)
        release = asyncio.Event()
        entered = asyncio.Event()

        async def holder():
            async with cap.slot():
                await release.wait()

        async def cancelled_waiter():
            async with cap.slot():
                pass  # pragma: no cover

        async def survivor():
            async with cap.slot():
                entered.set()

        h = asyncio.create_task(holder())
        await asyncio.sleep(0.01)
        cw = asyncio.create_task(cancelled_waiter())
        await asyncio.sleep(0.01)
        sv = asyncio.create_task(survivor())
        await asyncio.sleep(0.01)
        cw.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cw  # отмена не конвертируется в capacity-ошибку
        release.set()
        await h
        # слот не утёк: выживший дожидается своей очереди (пин семафора 3.13)
        await asyncio.wait_for(sv, timeout=1)
        assert entered.is_set()

    asyncio.run(main())
