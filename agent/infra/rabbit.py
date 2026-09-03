"""Консьюмер Событий RabbitMQ (тикет 005): topic exchange `events`, очередь bind `#`.

Auto-ack — гарантии дают БД (журнал instance_events) + чекпоинты, не ack-семантика.
Соединение — connect_robust (авто-reconnect). Обработка каждого сообщения — своим
asyncio-таском: ожидание слота одним Событием не блокирует очередь.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import aio_pika

from core.runner.events import Event, parse_event
from pkg.logger import get_logger

log = get_logger(__name__)

EXCHANGE = "events"
QUEUE = "events.runners"  # одна durable-очередь на всех раннеров (competing consumers)


async def consume_events(url: str, handler: Callable[[Event], Awaitable[str]]) -> None:
    """Потреблять События вечно; отмена таска — единственный выход."""
    connection = await aio_pika.connect_robust(url)
    tasks: set[asyncio.Task] = set()
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
        )
        queue = await channel.declare_queue(QUEUE, durable=True)
        await queue.bind(exchange, "#")
        log.info("consuming events", queue=QUEUE, exchange=EXCHANGE)
        async with queue.iterator(no_ack=True) as messages:
            async for message in messages:
                try:
                    event = parse_event(json.loads(message.body))
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    log.warning("unparseable event message dropped", body=message.body[:500])
                    continue
                task = asyncio.create_task(_handle(handler, event))
                tasks.add(task)
                task.add_done_callback(tasks.discard)


async def _handle(handler: Callable[[Event], Awaitable[str]], event: Event) -> None:
    try:
        outcome = await handler(event)
        log.info(
            "event handled", event_id=event.event_id, instance_id=event.instance_id, outcome=outcome
        )
    except Exception:
        log.warning(
            "event handling failed (processed_at not set; re-publish will retry)",
            event_id=event.event_id,
            instance_id=event.instance_id,
            exc_info=True,
        )
