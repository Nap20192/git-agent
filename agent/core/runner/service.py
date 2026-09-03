"""RunnerService: слоты, клейм/форвард/дедуп Событий, idle-выгрузка, heartbeat."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from core.runner.events import Event
from core.runner.executor import EventExecutor
from core.runner.ports import ClaimResult, HubClient, InstanceStore
from pkg.logger import get_logger

log = get_logger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 10.0
IDLE_SCAN_INTERVAL_SECONDS = 30.0


@dataclass
class LocalInstance:
    """Экземпляр Агента, поднятый в слоте этого раннера."""

    id: int
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_activity: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.last_activity = time.monotonic()


class RunnerService:
    def __init__(
        self,
        *,
        store: InstanceStore,
        hub: HubClient,
        executor: EventExecutor,
        name: str,
        address: str,
        slots: int,
        idle_timeout_seconds: float,
    ) -> None:
        self._store = store
        self._hub = hub
        self._executor = executor
        self.name = name
        self.address = address
        self.slots = slots
        self._idle_timeout = idle_timeout_seconds
        self._free = asyncio.Semaphore(slots)
        self._instances: dict[int, LocalInstance] = {}
        self._raise_lock = (
            asyncio.Lock()
        )  # ponytail: один замок на все подъёмы; per-instance при contention
        self._runner_id: int | None = None

    @property
    def busy(self) -> int:
        return len(self._instances)

    @property
    def runner_id(self) -> int:
        if self._runner_id is None:
            raise RuntimeError("runner is not registered yet; call start()")
        return self._runner_id

    async def start(self) -> None:
        """Регистрация: строка hub.runners (источник runner_id) + backend API (warn+retry)."""
        self._runner_id = await self._store.register_runner(
            name=self.name, address=self.address, slots=self.slots
        )
        await self._hub.register(name=self.name, address=self.address, slots=self.slots)
        log.info("runner registered", runner_id=self._runner_id, name=self.name)

    async def shutdown(self) -> None:
        """Опустить все поднятые Экземпляры (running→down)."""
        for instance_id in list(self._instances):
            await self.stop_instance(instance_id)

    async def _raise(self, instance_id: int) -> LocalInstance | ClaimResult:
        """Поднять Экземпляр в слот (идемпотентно) либо вернуть ClaimResult-отказ.

        Слот ждётся ВНЕ _raise_lock: иначе один ожидающий подъём стопорит
        обращения к уже поднятым Экземплярам (чат/События).
        """
        existing = self._instances.get(instance_id)
        if existing is not None:
            existing.touch()
            return existing
        await self._free.acquire()
        raised = False
        try:
            async with self._raise_lock:
                existing = self._instances.get(instance_id)
                if existing is not None:  # подняли, пока мы ждали слот
                    existing.touch()
                    return existing
                claim = await self._store.claim_instance(instance_id, runner_id=self.runner_id)
                if claim.outcome not in ("claimed", "held_by_self"):
                    return claim
                instance = LocalInstance(id=instance_id)
                self._instances[instance_id] = instance
                raised = True
                log.info("instance raised", instance_id=instance_id)
                return instance
        finally:
            if not raised:
                self._free.release()

    async def raise_instance(self, instance_id: int) -> bool:
        return isinstance(await self._raise(instance_id), LocalInstance)

    async def stop_instance(self, instance_id: int) -> bool:
        instance = self._instances.pop(instance_id, None)
        if instance is None:
            return False
        async with instance.lock:  # дождаться текущего хода
            await self._store.release_instance(instance_id, runner_id=self.runner_id)
        self._free.release()
        log.info("instance released", instance_id=instance_id)
        return True

    async def handle_event(self, event: Event) -> str:
        """Обработать Событие: клейм → локально либо форвард держателю → дедуп → исполнение.

        Возвращает исход: processed | duplicate | forwarded | dropped.
        Исключение исполнения пробрасывается (processed_at не ставится — Событие
        доисполнит ре-публикация backend'а).
        """
        # ponytail: чужое Событие тоже проходит через ожидание слота (слот берётся до
        # клейма); peek держателя без слота — если задержка форварда станет проблемой
        raised = await self._raise(event.instance_id)
        if isinstance(raised, ClaimResult):
            if raised.outcome == "held_by_other" and raised.holder_address:
                ok = await self._hub.forward_event(raised.holder_address, event)
                if ok:
                    return "forwarded"
                log.warning(
                    "event holder unreachable, dropping until re-publish",
                    instance_id=event.instance_id,
                    holder=raised.holder_address,
                )
                return "dropped"
            log.warning(
                "event for unclaimable instance",
                instance_id=event.instance_id,
                outcome=raised.outcome,
            )
            return "dropped"
        if not await self._store.begin_event(event):
            raised.touch()
            return "duplicate"
        async with raised.lock:
            raised.touch()
            ctx = await self._store.load_context(event.instance_id)
            if ctx is None:
                log.warning("instance context missing", instance_id=event.instance_id)
                return "dropped"
            await self._executor.process_event(ctx, event)
            await self._store.mark_processed(event.instance_id, event.dedup_key)
            raised.touch()
        return "processed"

    async def chat(self, instance_id: int, message: str):
        """Ход чата в тред Экземпляра; поднимает его при необходимости."""
        raised = await self._raise(instance_id)
        if isinstance(raised, ClaimResult):
            raise RuntimeError(f"instance {instance_id} unavailable: {raised.outcome}")
        async with raised.lock:
            raised.touch()
            ctx = await self._store.load_context(instance_id)
            if ctx is None:
                raise RuntimeError(f"instance {instance_id} context missing")
            async for item in self._executor.chat_stream(ctx, message):
                yield item
            raised.touch()

    async def heartbeat_loop(self) -> None:
        while True:
            try:
                await self._store.heartbeat_runner(self.runner_id)
                await self._hub.heartbeat(runner_id=self.runner_id)
            except Exception:
                log.warning("heartbeat failed", exc_info=True)
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

    async def reap_idle(self) -> None:
        """Один проход: выгрузить Экземпляры без активности дольше idle-таймаута."""
        now = time.monotonic()
        for instance_id, instance in list(self._instances.items()):
            if instance.lock.locked():
                continue
            if now - instance.last_activity > self._idle_timeout:
                log.info("idle timeout, unloading", instance_id=instance_id)
                await self.stop_instance(instance_id)

    async def idle_loop(self) -> None:
        while True:
            await asyncio.sleep(min(IDLE_SCAN_INTERVAL_SECONDS, self._idle_timeout))
            await self.reap_idle()
