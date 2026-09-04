"""Чекпоинтер LangGraph над пулом Postgres, устойчивый к отмене хода.

Стоп хода (`RunnerService.stop`) отменяет задачу хода; если CancelledError
прилетает внутрь операции AsyncPostgresSaver (взято соединение пула, открыт
pipeline), соединение может не вернуться в пул — после нескольких стопов пул
исчерпан и любой новый ход падает с PoolTimeout на первом же aget_state.
Операции чекпоинта короткие (миллисекунды), поэтому каждую доводим до конца
под asyncio.shield: отмена дойдёт до вызывающего сразу после операции, а
соединение вернётся в пул.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


class ShieldedPostgresSaver(AsyncPostgresSaver):
    async def aget_tuple(self, config: Any) -> Any:
        return await asyncio.shield(super().aget_tuple(config))

    async def aput(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        return await asyncio.shield(super().aput(config, checkpoint, metadata, new_versions))

    async def aput_writes(
        self, config: Any, writes: Any, task_id: str, task_path: str = ""
    ) -> None:
        await asyncio.shield(super().aput_writes(config, writes, task_id, task_path))

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.shield(super().adelete_thread(thread_id))


def make_checkpointer_pool(database_url: str, *, max_size: int) -> AsyncConnectionPool:
    """Пул под чекпоинтер (autocommit + без prepared statements, как требует saver);
    открывать `await pool.open(wait=True)`, закрывать `await pool.close()`."""
    return AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=max_size,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
