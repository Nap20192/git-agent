"""Событие (CONTEXT.md): тонкий факт с вебхука, приходит из RabbitMQ camelCase-JSON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Действия, у которых ход имеет смысл и без коммита (full_scan — HEAD клона,
# manual — сравнение с предыдущим разобранным коммитом / HEAD~1)
ACTIONS_WITHOUT_COMMIT = frozenset({"full_scan", "manual"})
PR_ACTIONS = frozenset({"pull_request", "merge_request"})


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
    trace_id: str = ""  # сквозной trace_id (pkg/trace); "" — сообщение до миграции 004
    # необязательные поля скоупа (hub заполняет, когда провайдер дал)
    before_sha: str | None = None  # push: состояние ветки до пуша
    base_sha: str | None = None  # PR/MR: база
    head_sha: str | None = None  # PR/MR: голова
    pr_number: int | None = None
    pr_title: str | None = None
    pr_body: str | None = None
    changed_files: tuple[str, ...] = ()

    @property
    def has_code_target(self) -> bool:
        """Есть ли что аудитить: коммит/голова PR либо действие, живущее без коммита.
        Иначе (ping, issues, comments…) ход не поднимается — skipped_no_commit."""
        return bool(self.commit_sha or self.head_sha) or self.action in ACTIONS_WITHOUT_COMMIT

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "eventId": self.event_id,
            "instanceId": self.instance_id,
            "threadId": self.thread_id,
            "repositoryId": self.repository_id,
            "provider": self.provider,
            "action": self.action,
            "dedupKey": self.dedup_key,
            "commitSha": self.commit_sha,
            "ref": self.ref,
            "traceId": self.trace_id,
        }
        optional = {
            "beforeSha": self.before_sha,
            "baseSha": self.base_sha,
            "headSha": self.head_sha,
            "prNumber": self.pr_number,
            "prTitle": self.pr_title,
            "prBody": self.pr_body,
            "changedFiles": list(self.changed_files) or None,
        }
        wire.update({k: v for k, v in optional.items() if v is not None})
        return wire


def _opt_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return str(value) if value not in (None, "") else None


def _opt_sha(data: dict[str, Any], key: str) -> str | None:
    """Нулевой sha (первый пуш ветки / удаление) провайдеры шлют как значение — для нас его нет."""
    value = _opt_str(data, key)
    return None if value is not None and set(value) == {"0"} else value


def parse_event(data: dict[str, Any]) -> Event:
    """Разобрать wire-JSON в Событие; неполное сообщение — ValueError.
    Поля скоупа (beforeSha, baseSha, headSha, prNumber, prTitle, prBody, changedFiles)
    необязательны — старые сообщения разбираются как прежде."""
    try:
        files = data.get("changedFiles") or ()
        if not isinstance(files, (list, tuple)):
            raise TypeError("changedFiles must be a list")
        pr_number = data.get("prNumber")
        return Event(
            event_id=int(data["eventId"]),
            instance_id=int(data["instanceId"]),
            thread_id=str(data["threadId"]),
            repository_id=int(data["repositoryId"]),
            provider=str(data["provider"]),
            action=str(data["action"]),
            dedup_key=str(data["dedupKey"]),
            commit_sha=_opt_sha(data, "commitSha"),
            ref=_opt_str(data, "ref"),
            trace_id=str(data.get("traceId") or ""),
            before_sha=_opt_sha(data, "beforeSha"),
            base_sha=_opt_sha(data, "baseSha"),
            head_sha=_opt_sha(data, "headSha"),
            pr_number=int(pr_number) if pr_number not in (None, "") else None,
            pr_title=_opt_str(data, "prTitle"),
            pr_body=_opt_str(data, "prBody"),
            changed_files=tuple(str(f) for f in files),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"bad event message: {exc!r}") from exc
