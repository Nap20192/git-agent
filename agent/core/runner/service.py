"""RunnerService: слоты, клейм/форвард/дедуп Событий, idle-выгрузка, heartbeat."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from structlog.contextvars import bound_contextvars

from core.runner.activity import ActivityCollector, ActivityFeed, ActivityTurn
from core.runner.events import Event
from core.runner.executor import EventExecutor
from core.runner.ports import (
    ClaimResult,
    HubClient,
    InstanceStore,
    InstanceUnavailableError,
    SandboxNotProvisionedError,
)
from pkg import trace
from pkg.errors import describe
from pkg.logger import get_logger

log = get_logger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 10.0
IDLE_SCAN_INTERVAL_SECONDS = 30.0
# сколько raise ждёт слот, прежде чем ответить queued и поднимать фоном
# (hub-прокси не готов ждать слот HTTP-запросом — прод-бага context deadline exceeded)
RAISE_WAIT_SECONDS = 1.0


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _log_task_failure(task: asyncio.Task) -> None:
    """Фоновый таск упал — иначе исключение всплывёт лишь как 'never retrieved' при GC."""
    if not task.cancelled() and task.exception() is not None:
        log.error("background task failed", task=task.get_name(), error=describe(task.exception()))


@dataclass
class LocalInstance:
    """Экземпляр Агента, поднятый в слоте этого раннера."""

    id: int
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_activity: float = field(default_factory=time.monotonic)
    term_cwd: str | None = None  # рабочая директория стрим-консоли; живёт пока Экземпляр поднят
    # лок ТОЛЬКО консоли (последовательность команд одного оператора, cwd); с `lock`
    # хода не пересекается — терминал не ждёт, пока Лид думает
    term_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    turn_task: asyncio.Task | None = None  # исполняющийся ход События; цель stop_instance

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
        self._activity = ActivityFeed()
        self._pending_raises: set[asyncio.Task] = set()  # queued-подъёмы, ждущие слот фоном

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
                    log.info(
                        "instance claim rejected",
                        instance_id=instance_id,
                        outcome=claim.outcome,
                        holder=claim.holder_address,
                    )
                    return claim
                instance = LocalInstance(id=instance_id)
                self._instances[instance_id] = instance
                raised = True
                log.info("instance raised", instance_id=instance_id)
                return instance
        finally:
            if not raised:
                self._free.release()

    async def raise_instance(self, instance_id: int) -> str:
        """Быстрый подъём: running | queued | rejected.

        Ответ не ждёт слот дольше RAISE_WAIT_SECONDS: занятые слоты — queued,
        подъём продолжается фоном и завершится, когда слот освободится.
        """
        task = asyncio.create_task(self._raise(instance_id), name=f"raise-{instance_id}")
        done, _ = await asyncio.wait({task}, timeout=RAISE_WAIT_SECONDS)
        if not done:
            self._pending_raises.add(task)
            task.add_done_callback(self._pending_raises.discard)
            task.add_done_callback(_log_task_failure)
            log.info("instance raise queued: no free slot", instance_id=instance_id)
            return "queued"
        return "running" if isinstance(task.result(), LocalInstance) else "rejected"

    async def stop_instance(self, instance_id: int) -> bool:
        instance = self._instances.pop(instance_id, None)
        if instance is None:
            return False
        if instance.turn_task is not None:
            # честный стоп: отменить исполняющийся ход; Событие остаётся
            # незавершённым (processed_at NULL), чекпоинт хранит готовые шаги
            instance.turn_task.cancel()
        async with instance.lock:  # дождаться отмены/завершения текущего хода
            await self._store.release_instance(instance_id, runner_id=self.runner_id)
        self._free.release()
        log.info("instance released", instance_id=instance_id)
        return True

    async def handle_event(self, event: Event) -> str:
        """Обработать Событие: клейм → локально либо форвард держателю → дедуп → исполнение.

        Возвращает исход: processed | duplicate | forwarded | dropped | cancelled |
        skipped_no_commit (Событие без коммита и не full_scan/manual — ход не поднимается).
        Исключение исполнения логируется здесь (один раз, с трейсбеком и контекстом
        хода) и пробрасывается: processed_at не ставится — Событие доисполнит
        ре-публикация backend'а.
        """
        started = time.monotonic()
        # trace_id: из сообщения (вебхук/trigger → outbox → Rabbit) либо из HTTP-контекста
        # форварда; сообщение до миграции 004 — новый
        trace_id = event.trace_id or trace.current_or_new()
        with bound_contextvars(
            instance_id=event.instance_id, event_id=event.event_id, trace_id=trace_id
        ):
            log.info(
                "event received",
                provider=event.provider,
                action=event.action,
                ref=event.ref,
                commit=event.commit_sha,
            )
            try:
                outcome = await self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("turn failed", error=describe(exc), duration_ms=_ms(started))
                raise
            log.info("event handled", outcome=outcome, duration_ms=_ms(started))
            return outcome

    async def _handle_event(self, event: Event) -> str:
        if not event.has_code_target:
            # ping/issues/comments…: ход не поднимаем вовсе; processed_at ставим,
            # чтобы hub не ре-публиковал Событие
            if await self._store.begin_event(event):
                await self._store.mark_processed(event.instance_id, event.dedup_key)
            log.info("event without code target skipped", action=event.action)
            return "skipped_no_commit"
        # чужое/пропавшее — определяем ДО ожидания слота (peek без клейма);
        # гонку peek→claim решает CAS: _raise вернёт held_by_other и мы форварднём
        if event.instance_id not in self._instances:
            peek = await self._store.peek_holder(event.instance_id, runner_id=self.runner_id)
            if peek.outcome in ("held_by_other", "missing"):
                return await self._hand_off(event, peek)
        raised = await self._raise(event.instance_id)
        if isinstance(raised, ClaimResult):
            return await self._hand_off(event, raised)
        if not await self._store.begin_event(event):
            raised.touch()
            return "duplicate"
        async with raised.lock:
            raised.touch()
            ctx = await self._store.load_context(event.instance_id)
            if ctx is None:
                log.warning("instance context missing", instance_id=event.instance_id)
                return "dropped"
            turn = self._begin_turn(event.instance_id, event.event_id)
            collector = ActivityCollector()

            async def on_chunk(mode: str, data) -> None:
                for frame in collector.frames(mode, data):
                    await turn.emit(frame)

            await turn.emit(collector.run_started())
            exec_task = asyncio.create_task(
                self._executor.process_event(ctx, event, on_chunk=on_chunk)
            )
            raised.turn_task = exec_task
            try:
                await exec_task
            except asyncio.CancelledError:
                if not exec_task.cancelled():  # отменили нас (shutdown) — погасить ход
                    exec_task.cancel()
                    raise
                # штатный стоп хода: processed_at не ставится — «Продолжить»
                # доисполнит Событие с чекпоинта (готовые шаги сохранены)
                log.warning(
                    "turn cancelled by stop",
                    instance_id=event.instance_id,
                    event_id=event.event_id,
                )
                await turn.emit(collector.run_failed("ход остановлен"))
                return "cancelled"
            except SandboxNotProvisionedError as exc:
                # песочницу создаёт юзер в UI; без неё Событие не обрабатываем
                # (processed_at не ставится — ре-публикация доисполнит после создания)
                log.warning("sandbox not provisioned, event dropped", reason=str(exc))
                await turn.emit(collector.run_failed(f"sandbox not provisioned: {exc}"))
                return "dropped"
            except Exception as exc:
                await turn.emit(collector.run_failed(describe(exc)))
                raise
            else:
                await turn.emit(collector.run_finished())
            finally:
                raised.turn_task = None
                turn.close()
            await self._store.mark_processed(event.instance_id, event.dedup_key)
            raised.touch()
        return "processed"

    async def _hand_off(self, event: Event, claim: ClaimResult) -> str:
        """Событие не наше: форвард держателю либо drop (доисполнит ре-публикация)."""
        if claim.outcome == "held_by_other" and claim.holder_address:
            if await self._hub.forward_event(claim.holder_address, event):
                return "forwarded"
            log.warning(
                "event holder unreachable, dropping until re-publish",
                instance_id=event.instance_id,
                holder=claim.holder_address,
            )
            return "dropped"
        log.warning(
            "event for unclaimable instance",
            instance_id=event.instance_id,
            outcome=claim.outcome,
        )
        return "dropped"

    async def chat(self, instance_id: int, message: str):
        """Ход чата в тред Экземпляра; поднимает его при необходимости.

        Ошибка хода логируется здесь (с трейсбеком) и пробрасывается вызывающему,
        который переводит её в кадр стрима.
        """
        started = time.monotonic()
        with bound_contextvars(
            instance_id=instance_id, turn="chat", trace_id=trace.current_or_new()
        ):
            raised = await self._raise(instance_id)
            if isinstance(raised, ClaimResult):
                raise InstanceUnavailableError(instance_id, raised.outcome)
            async with raised.lock:
                raised.touch()
                ctx = await self._store.load_context(instance_id)
                if ctx is None:
                    raise InstanceUnavailableError(instance_id, "context missing")
                log.info("chat turn started", chars=len(message))
                turn = self._begin_turn(instance_id, None)  # event_id NULL — ход чата
                collector = ActivityCollector()
                await turn.emit(collector.run_started())
                try:
                    async for mode, data in self._executor.chat_stream(ctx, message):
                        for frame in collector.frames(mode, data):
                            await turn.emit(frame)
                        yield mode, data
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.exception("chat turn failed", error=describe(exc), duration_ms=_ms(started))
                    await turn.emit(collector.run_failed(describe(exc)))
                    raise
                else:
                    log.info("chat turn finished", duration_ms=_ms(started))
                    await turn.emit(collector.run_finished())
                finally:
                    turn.close()
                raised.touch()

    def _begin_turn(self, instance_id: int, event_id: int | None) -> ActivityTurn:
        """Открыть activity-ход; персист кадров best-effort (ход важнее журнала).
        trace_id хода (contextvars) — в каждый кадр и в hub.activity.trace_id."""
        trace_id = trace.current_or_new()

        async def persist(seq: int, frame: dict) -> None:
            try:
                await self._store.add_activity(
                    instance_id, event_id=event_id, seq=seq, frame=frame, trace_id=trace_id
                )
            except Exception as exc:
                log.warning("activity persist failed", seq=seq, error=describe(exc))

        return self._activity.begin(instance_id, event_id, persist, trace_id=trace_id)

    async def activity(self, instance_id: int, *, event_id: int | None = None):
        """Кадры хода: живой — реплей буфера + live; завершённый — из hub.activity
        (event_id=None ⇒ живой либо последний ход)."""
        turn = self._activity.live(instance_id)
        if turn is not None and (event_id is None or turn.event_id == event_id):
            async for frame in turn.stream():
                yield frame
            return
        for frame in await self._store.list_activity(
            instance_id, event_id=event_id, latest=event_id is None
        ):
            yield frame

    async def terminal(self, instance_id: int, command: str) -> tuple[str, int | None, str | None]:
        """Команда стрим-консоли в песочнице Экземпляра; поднимает его при необходимости.

        НЕ берёт lock хода: консоли нужны только поднятый Экземпляр и живая песочница,
        execd исполняет команды параллельно с ходом агента. Осознанно: команды оператора
        и агента могут гонять за одни файлы в /repo — это консоль оператора, не транзакция.
        Свой term_lock — только последовательность команд и cwd; touch держит idle-таймер.
        """
        with bound_contextvars(
            instance_id=instance_id, turn="terminal", trace_id=trace.current_or_new()
        ):
            raised = await self._raise(instance_id)
            if isinstance(raised, ClaimResult):
                raise InstanceUnavailableError(instance_id, raised.outcome)
            async with raised.term_lock:
                raised.touch()
                ctx = await self._store.load_context(instance_id)
                if ctx is None:
                    raise InstanceUnavailableError(instance_id, "context missing")
                output, code, new_cwd = await self._executor.terminal(ctx, command, raised.term_cwd)
                log.info("terminal command finished", exit_code=code, output_chars=len(output))
                if new_cwd:
                    raised.term_cwd = new_cwd
                raised.touch()
                return output, code, new_cwd

    async def heartbeat_loop(self) -> None:
        while True:
            try:
                await self._store.heartbeat_runner(self.runner_id)
                await self._hub.heartbeat(runner_id=self.runner_id)
            except Exception as exc:
                log.warning("heartbeat failed, will retry", error=describe(exc))
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

    async def reap_idle(self) -> None:
        """Один проход: выгрузить Экземпляры без активности дольше idle-таймаута."""
        now = time.monotonic()
        for instance_id, instance in list(self._instances.items()):
            if instance.lock.locked() or instance.term_lock.locked():
                continue
            if now - instance.last_activity > self._idle_timeout:
                log.info("idle timeout, unloading", instance_id=instance_id)
                await self.stop_instance(instance_id)

    async def idle_loop(self) -> None:
        while True:
            await asyncio.sleep(min(IDLE_SCAN_INTERVAL_SECONDS, self._idle_timeout))
            await self.reap_idle()
