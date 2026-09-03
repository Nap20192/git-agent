"""Раннер (CONTEXT.md): консьюмер Событий, слоты Экземпляров Агентов.

Wiring: RabbitMQ (infra/rabbit.py) и HTTP API (infra/server/runner_api.py) зовут
RunnerService.handle_event/chat/…; сервис ходит в hub.* через порт InstanceStore
(адаптер infra/db/hub_store.py) и в backend через HubClient (infra/hub_client.py);
исполнение — EventExecutor поверх lead-профиля с hub-тулзами результатов.
Composition root — runner.py в корне agent/.
"""

from core.runner.events import Event, parse_event
from core.runner.service import RunnerService

__all__ = ["Event", "RunnerService", "parse_event"]
