"""HTTP-адаптер порта HubClient: регистрация/heartbeat в backend + форвард Событий.

Backend (hub) ещё пишется: пути зафиксированы спекой runner, сетевые сбои
деградируют в warning — раннер продолжает работать; повтор регистрации едет
с каждым heartbeat'ом (сам heartbeat-роут делает upsert по имени).
"""

from __future__ import annotations

import httpx

from core.runner.events import Event
from pkg.logger import get_logger

log = get_logger(__name__)

TIMEOUT_SECONDS = 10.0


class HttpHubClient:
    def __init__(self, *, backend_url: str, token: str) -> None:
        self._backend = backend_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            headers={"X-Runner-Token": token} if token else {},
        )
        self._registration: dict | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def register(self, *, name: str, address: str, slots: int) -> None:
        self._registration = {"name": name, "address": address, "slots": slots}
        await self._post(f"{self._backend}/api/runners", self._registration)

    async def heartbeat(self, *, name: str) -> None:
        # ре-регистрация тем же роутом: upsert по имени двигает last_heartbeat_at
        if self._registration is not None:
            await self._post(f"{self._backend}/api/runners", self._registration)

    async def forward_event(self, address: str, event: Event) -> bool:
        url = f"{address.rstrip('/')}/instances/{event.instance_id}/events"
        try:
            response = await self._client.post(url, json=event.to_wire())
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            log.warning("event forward failed", url=url, event_id=event.event_id)
            return False

    async def _post(self, url: str, payload: dict) -> None:
        if not self._backend:
            return  # backend не сконфигурирован — работаем автономно
        try:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("backend unreachable, will retry", url=url, error=str(exc))
