"""HTTP-адаптер порта HubClient: регистрация/heartbeat в hub + форвард Событий.

Контракт — backend/docs/openapi.yaml (ветка hub): POST /api/runners (201 + Runner),
POST /api/runners/{id}/heartbeat (204; 404 = hub нас не знает → ре-регистрация).
Auth — X-Runner-Token. Каждый запрос несёт X-Trace-Id (pkg/trace): из контекста
хода, иначе свой. hub недоступен → warn, раннер работает дальше (retry
едет с каждым heartbeat'ом).
"""

from __future__ import annotations

import httpx

from core.runner.events import Event
from pkg import trace
from pkg.errors import describe
from pkg.logger import get_logger

log = get_logger(__name__)

TIMEOUT_SECONDS = 10.0


class HttpHubClient:
    def __init__(
        self, *, hub_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._hub = hub_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            headers={"X-Runner-Token": token} if token else {},
            transport=transport,
        )
        self._registration: dict | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _headers(trace_id: str | None = None) -> dict[str, str]:
        return {trace.HEADER: trace_id or trace.current_or_new()}

    async def register(self, *, name: str, address: str, slots: int) -> None:
        self._registration = {"name": name, "address": address, "slots": slots}
        await self._try_register()

    async def _try_register(self) -> None:
        if not self._hub or self._registration is None:
            return
        url = f"{self._hub}/api/runners"
        try:
            response = await self._client.post(
                url, json=self._registration, headers=self._headers()
            )
            response.raise_for_status()
            log.info("registered with hub", runner=response.json().get("id"))
        except httpx.HTTPError as exc:
            log.warning("hub registration failed, will retry", url=url, error=str(exc))

    async def heartbeat(self, *, runner_id: int) -> None:
        if not self._hub:
            return
        url = f"{self._hub}/api/runners/{runner_id}/heartbeat"
        try:
            response = await self._client.post(url, headers=self._headers())
            if response.status_code == 404:  # hub нас не знает — ре-регистрация
                log.warning("hub does not know this runner, re-registering", runner_id=runner_id)
                await self._try_register()
                return
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("hub heartbeat failed, will retry", url=url, error=str(exc))

    async def forward_event(self, address: str, event: Event) -> bool:
        url = f"{address.rstrip('/')}/instances/{event.instance_id}/events"
        try:
            response = await self._client.post(
                url, json=event.to_wire(), headers=self._headers(event.trace_id)
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.warning(
                "event forward failed", url=url, event_id=event.event_id, error=describe(exc)
            )
            return False
