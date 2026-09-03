"""Событие (CONTEXT.md): тонкий факт с вебхука, приходит из RabbitMQ camelCase-JSON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Event:
    event_id: int
    instance_id: int
    thread_id: str
    repository_id: int
    provider: str
    action: str
    dedup_key: str
    commit_sha: str | None = None
    ref: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "eventId": self.event_id,
            "instanceId": self.instance_id,
            "threadId": self.thread_id,
            "repositoryId": self.repository_id,
            "provider": self.provider,
            "action": self.action,
            "dedupKey": self.dedup_key,
            "commitSha": self.commit_sha,
            "ref": self.ref,
        }


def parse_event(data: dict[str, Any]) -> Event:
    """Разобрать wire-JSON в Событие; неполное сообщение — ValueError."""
    try:
        return Event(
            event_id=int(data["eventId"]),
            instance_id=int(data["instanceId"]),
            thread_id=str(data["threadId"]),
            repository_id=int(data["repositoryId"]),
            provider=str(data["provider"]),
            action=str(data["action"]),
            dedup_key=str(data["dedupKey"]),
            commit_sha=data.get("commitSha") or None,
            ref=data.get("ref") or None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"bad event message: {exc!r}") from exc
