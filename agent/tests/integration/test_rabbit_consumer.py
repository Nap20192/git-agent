"""Консьюмер Событий против реального RabbitMQ: мусор переживается, Событие доходит."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from core.config import settings


def _rabbit_available() -> bool:
    import socket

    host_port = settings.rabbit_url.rsplit("@", 1)[-1].rstrip("/")
    host, _, port = host_port.partition(":")
    try:
        with socket.create_connection((host, int(port or 5672)), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _rabbit_available(), reason="rabbitmq is not running")

WIRE = {
    "eventId": 7,
    "instanceId": 3,
    "threadId": "inst-3",
    "repositoryId": 5,
    "provider": "github",
    "action": "push",
    "dedupKey": "abc123",
}


def test_consume_garbage_then_event(monkeypatch):
    import aio_pika

    import infra.rabbit as rabbit

    queue_name = f"test-runners-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(rabbit, "QUEUE", queue_name)

    async def main():
        received: list = []
        done = asyncio.Event()

        async def handler(event):
            received.append(event)
            done.set()
            return "processed"

        consumer = asyncio.create_task(rabbit.consume_events(settings.rabbit_url, handler))
        connection = await aio_pika.connect_robust(settings.rabbit_url)
        try:
            async with connection:
                channel = await connection.channel()
                # дождаться, пока консьюмер объявит и забиндит очередь
                for _ in range(100):
                    try:
                        await channel.declare_queue(queue_name, durable=True, passive=True)
                        break
                    except aio_pika.exceptions.ChannelClosed:
                        channel = await connection.channel()
                        await asyncio.sleep(0.05)
                exchange = await channel.declare_exchange(
                    rabbit.EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
                )
                for body in (b"not json", json.dumps({"eventId": 1}).encode(),
                             json.dumps(WIRE).encode()):
                    await exchange.publish(
                        aio_pika.Message(body), routing_key="github.5.push"
                    )
                await asyncio.wait_for(done.wait(), timeout=10)
                # мусор отброшен, валидное Событие разобрано
                assert [e.event_id for e in received] == [7]
                assert received[0].dedup_key == "abc123"
                await channel.queue_delete(queue_name)
        finally:
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await consumer

    asyncio.run(main())
