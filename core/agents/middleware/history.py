"""HistoryMiddleware — пишет всю историю работы агента в run_events.

Каждое новое сообщение (модель, инструменты) сохраняется по мере появления;
старт и финал агента фиксируются отдельными событиями. Сбой записи истории
логируется, но не роняет ран. Работает и в sync- (invoke), и в async-пути
(ainvoke) — async-хуки пишут через AsyncConnectionPool.
"""

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import message_to_dict

from infra.postgres import aadd_run_event, add_run_event
from pkg.logger import get_logger

log = get_logger(__name__)


class HistoryMiddleware(AgentMiddleware):
    def __init__(self, run_id: int) -> None:
        super().__init__()
        self.run_id = run_id
        self._seen_ids: set[str] = set()

    def _save(self, kind: str, payload: dict[str, Any]) -> None:
        try:
            add_run_event(self.run_id, kind, payload)
        except Exception:
            log.exception("run history write failed", run_id=self.run_id, kind=kind)

    def _save_new_messages(self, state: Any) -> None:
        for m in state.get("messages", []):
            if m.id in self._seen_ids:
                continue
            self._save("model_message", message_to_dict(m))
            if m.id is not None:
                self._seen_ids.add(m.id)

    def before_agent(self, state: Any, runtime: Any) -> None:
        self._save("agent_start", {"message_count": len(state.get("messages", []))})
        self._save_new_messages(state)

    def after_model(self, state: Any, runtime: Any) -> None:
        self._save_new_messages(state)

    def after_agent(self, state: Any, runtime: Any) -> None:
        self._save_new_messages(state)
        self._save("agent_finish", self._finish_payload(state))

    @staticmethod
    def _finish_payload(state: Any) -> dict[str, Any]:
        messages = state.get("messages", [])
        return {
            "message_count": len(messages),
            "final": message_to_dict(messages[-1]) if messages else None,
        }

    def _unseen(self, state: Any) -> list[Any]:
        return [m for m in state.get("messages", []) if m.id not in self._seen_ids]

    async def _asave(self, kind: str, payload: dict[str, Any]) -> None:
        try:
            await aadd_run_event(self.run_id, kind, payload)
        except Exception:
            log.exception("run history write failed", run_id=self.run_id, kind=kind)

    async def _asave_new_messages(self, state: Any) -> None:
        for m in self._unseen(state):
            await self._asave("model_message", message_to_dict(m))
            if m.id is not None:
                self._seen_ids.add(m.id)

    async def abefore_agent(self, state: Any, runtime: Any) -> None:
        await self._asave("agent_start", {"message_count": len(state.get("messages", []))})
        await self._asave_new_messages(state)

    async def aafter_model(self, state: Any, runtime: Any) -> None:
        await self._asave_new_messages(state)

    async def aafter_agent(self, state: Any, runtime: Any) -> None:
        await self._asave_new_messages(state)
        await self._asave("agent_finish", self._finish_payload(state))
