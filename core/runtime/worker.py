"""Воркер — data plane: единственная функция, реально крутящая граф Рана.

Порядок финализации: терминальная durable-запись — ПОСЛЕДНЕЕ durable-действие
(строка остаётся running на время cleanup, поэтому resume-claim не может
переплестись с финализирующимся предшественником). Fence (ownership_lost)
гейтит все durable-записи, но никогда — publish_end.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.errors import GraphRecursionError

from core.ports import RunStore, Sandbox, StreamBridge
from core.runtime.manager import RunManager
from core.runtime.profile import GraphProfile
from core.runtime.schemas import (
    STOP_REASON_CANCELLED,
    STOP_REASON_TURN,
    RunRecord,
    RunStartOutcome,
    RunStatus,
)
from core.runtime.serialization import serialize
from core.tracing import build_tracing_callbacks, inject_langfuse_metadata
from pkg.logger import get_logger

log = get_logger(__name__)


async def run_agent(
    *,
    manager: RunManager,
    store: RunStore,
    bridge: StreamBridge,
    record: RunRecord,
    run_row: dict[str, Any],
    repo_url: str,
    profile: GraphProfile,
    make_model: Callable[..., Any],
    create_sandbox: Callable[[str], Awaitable[Sandbox]],
    checkpointer: Any = None,
    sandbox_name: str = "git",
    is_resume: bool = False,
    checkout_ref: str | None = None,
    instructions: str | None = None,
) -> None:
    run_id = record.run_id
    outcome = RunStatus.succeeded
    error: str | None = None
    stop_reason: str | None = None
    report: dict[str, Any] | None = None
    sandbox: Sandbox | None = None
    usage_collector: Any = None

    try:
        if is_resume:
            # Сброс стрима прошлой инкарнации: снимает ended-флаг, иначе новые
            # подписчики получат преждевременный END_SENTINEL. Подписчики старой
            # инкарнации переподписываются по gap-контракту.
            await bridge.cleanup(run_id)
        try:
            sandbox = await create_sandbox(sandbox_name)
            model = make_model(
                model=run_row["llm_model"],
                api_base=run_row["llm_api_base"],
                api_key=run_row["llm_api_key"],
            )
            # Подготовка песочницы (например клон репо для лида); при resume
            # песочница новая — готовим заново, чекпоинт хранит только состояние графа.
            if profile.prepare is not None:
                await profile.prepare(sandbox, repo_url, checkout_ref)
            graph = profile.build(sandbox, model, checkpointer=checkpointer)
            # Коллбэки трейсинга — на корне инвокации: LangGraph прокидывает их
            # во все вложенные вызовы, один трейс деревом на ран. Ошибка сборки
            # (включён, но не настроен) — setup-ошибка рана, не тихий пропуск.
            tracing_callbacks = build_tracing_callbacks()
            # Usage-коллектор на корне: считает ВСЕ LLM-вызовы рана (лид,
            # pipeline-parse, сабагенты) с дедупом по run_id вызова
            from core.subagents.executor import SubagentTokenCollector

            usage_collector = SubagentTokenCollector(caller="run")
        except asyncio.CancelledError:
            outcome, stop_reason = RunStatus.interrupted, STOP_REASON_CANCELLED
            raise
        except Exception as exc:
            outcome, error = RunStatus.failed, f"setup: {exc}"
            log.exception("run setup failed", run_id=run_id)
            return

        # Барьер: отмена, догнавшая ран в pending, гарантирует «граф не стартовал»
        if await manager.try_start(run_id) is not RunStartOutcome.started:
            outcome, stop_reason = RunStatus.interrupted, STOP_REASON_CANCELLED
            return

        config: dict[str, Any] = {
            "configurable": {"thread_id": str(run_id)},
            "callbacks": [*tracing_callbacks, usage_collector],
            **profile.run_config,
        }
        inject_langfuse_metadata(config, thread_id=str(run_id), model_name=run_row["llm_model"])
        # resume: None как вход — LangGraph продолжает с чекпоинта
        graph_input = (
            None if is_resume else profile.make_input(repo_url, checkout_ref, instructions)
        )
        try:
            async for mode, chunk in graph.astream(
                graph_input, config=config, stream_mode=profile.stream_modes
            ):
                if record.abort_event.is_set():
                    outcome, stop_reason = RunStatus.interrupted, STOP_REASON_CANCELLED
                    break
                data = serialize(chunk, mode=mode)
                await bridge.publish(run_id, mode, data)
                try:
                    await store.add_event(run_id, mode, {"data": data})
                except Exception:
                    log.exception("event persistence failed", run_id=run_id)
            if outcome is RunStatus.succeeded:
                state = await graph.aget_state(config)
                report = profile.extract_report(state.values or {})
                if report is not None and report.get("error"):
                    outcome, error = RunStatus.failed, str(report["error"])
        except asyncio.CancelledError:
            outcome, stop_reason = RunStatus.interrupted, STOP_REASON_CANCELLED
            raise
        except GraphRecursionError:
            # Исчерпан бюджет ходов — не крах, а частичный результат (turn_capped):
            # достаём отчёт из последнего сохранённого состояния.
            stop_reason = STOP_REASON_TURN
            log.warning("run hit recursion limit; harvesting partial report", run_id=run_id)
            try:
                state = await graph.aget_state(config)
                report = profile.extract_report(state.values or {})
            except Exception:
                report = None
            if report is not None and not report.get("error"):
                outcome = RunStatus.succeeded  # capped, но с выводом
            else:
                outcome, error = RunStatus.failed, "reached max turns without an answer"
        except Exception as exc:
            outcome, error = RunStatus.failed, str(exc)
            log.exception("run failed", run_id=run_id)
            with contextlib.suppress(Exception):
                await bridge.publish(run_id, "error", {"error": str(exc)})
    except asyncio.CancelledError:
        pass  # финализация в finally; не проглатываем смысл, статус уже выставлен
    finally:
        record.finalizing = True

        async def _finalization() -> None:
            try:
                if sandbox is not None:
                    await _close_quietly(sandbox)
                # Терминальное usage-событие (контракт eval-харнеса) — на ЛЮБОМ
                # исходе (succeeded/turn_capped/failed/cancelled): потраченные
                # токены — факт, независимый от статуса. Одно событие на попытку;
                # харнес суммирует по всем попыткам. Best-effort, ран не роняет.
                if usage_collector is not None and not record.ownership_lost:
                    try:
                        usage_payload = {
                            "type": "usage",
                            "usage": usage_collector.cumulative_usage(),
                            "llm_calls": len(usage_collector.snapshot_records()),
                            "records": usage_collector.snapshot_records(),
                        }
                        await bridge.publish(run_id, "custom", usage_payload)
                        await store.add_event(run_id, "usage", usage_payload)
                    except Exception:
                        log.exception("usage event emission failed", run_id=run_id)
                if not record.ownership_lost:
                    await _finalize(
                        store,
                        manager,
                        record,
                        outcome=outcome,
                        error=error,
                        stop_reason=stop_reason,
                        report=report,
                    )
                else:
                    log.warning("fenced: skipping durable finalization", run_id=run_id)
            finally:
                await bridge.publish_end(run_id)  # безусловно, даже при fence

        # Поздние task.cancel() (shutdown, второй cancel, fence) не должны
        # рвать финализацию посередине: одиночный shield этого НЕ гарантирует —
        # await на shield сам отменяем. Крутим shield в цикле до завершения.
        fut = asyncio.ensure_future(_finalization())
        while not fut.done():
            try:
                await asyncio.shield(fut)
            except asyncio.CancelledError:
                continue
        if not fut.cancelled() and fut.exception() is not None:
            log.error("finalization failed", run_id=run_id, error=str(fut.exception()))
        record.finalizing = False
        _spawn(bridge.cleanup(run_id, delay=60))
        manager.evict_later(record)


async def _finalize(
    store: RunStore,
    manager: RunManager,
    record: RunRecord,
    *,
    outcome: RunStatus,
    error: str | None,
    stop_reason: str | None,
    report: dict[str, Any] | None,
) -> None:
    run_id = record.run_id
    if outcome is RunStatus.succeeded:
        fin = await store.finalize_if_not_cancelled(
            run_id, owner_worker_id=manager.worker_id, report=report
        )
        if fin.finalized:
            record.status = RunStatus.succeeded
        elif fin.cancelled:
            # отмена победила на финишной ленте — честный interrupted
            await store.finish(
                run_id,
                owner_worker_id=manager.worker_id,
                status=RunStatus.interrupted,
                stop_reason=STOP_REASON_CANCELLED,
            )
            record.status = RunStatus.interrupted
        else:
            # не можем доказать, кто победил — fence, никаких записей
            manager.mark_ownership_lost(run_id)
    else:
        wrote = await store.finish(
            run_id,
            owner_worker_id=manager.worker_id,
            status=outcome,
            error=error,
            stop_reason=stop_reason,
        )
        if wrote:
            record.status = outcome
            return
        # CAS не прошёл: если строка уже терминальна (например, try_start сам
        # дописал interrupted при отмене-в-полёте) — принять её статус; fence
        # только при реальной потере владения (строка активна у другого).
        row = await store.get(run_id)
        if row is not None and row["status"] in (
            RunStatus.succeeded,
            RunStatus.failed,
            RunStatus.interrupted,
        ):
            record.status = RunStatus(row["status"])
        else:
            manager.mark_ownership_lost(run_id)


async def _close_quietly(sandbox: Sandbox) -> None:
    try:
        await sandbox.close()
    except Exception:
        log.exception("sandbox close failed")


_background: set[asyncio.Task] = set()


def _spawn(coro: Awaitable[None]) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
