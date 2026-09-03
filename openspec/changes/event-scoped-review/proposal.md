# event-scoped-review

## Why

На любое Событие с коммитом Лид получал одно и то же задание «разбери Событие», а на `full_scan` — полный аудит; на push/PR агент склонялся сканировать весь репозиторий, тратя ход на код, который не менялся. События без кода (ping, issues, comments) поднимали Экземпляр и ход впустую. Hub параллельно добавляет в Событие поля скоупа (`beforeSha`, `baseSha`/`headSha`, `prNumber`/`prTitle`/`prBody`, `changedFiles`) — раннер должен их принять и использовать.

## What Changes

- `Event` принимает необязательные поля скоупа (обратная совместимость; нулевой sha провайдера = отсутствие значения); `to_wire` их сохраняет при форварде.
- Задание хода по типу События (`executor._event_prompt`): `push` — аудит только изменений `beforeSha..commitSha` (без `beforeSha` — HEAD~1 с оговоркой), `pull_request`/`merge_request` — ревью диффа `merge-base...headSha` с заголовком/описанием PR как контекстом намерения, оценкой attack surface и `write_report` как PR-ревью; `manual` — от предыдущего разобранного коммита треда либо HEAD~1; `full_scan` — без изменений.
- Перед ходом раннер догружает в shallow-клон коммиты скоупа (`ensure_commits`: fetch по sha, для PR — merge-base с `--unshallow` при нужде).
- События без коммита и не `full_scan`/`manual` — ход не поднимается: outcome `skipped_no_commit`, `processed_at` ставится (без ре-публикации).

## Capabilities

### Modified Capabilities

- `runner`: «Консьюмер Событий RabbitMQ» (поля скоупа), «Исполнение События Экземпляром» (коммиты скоупа в песочнице, задание по типу События), новое требование о Событиях без кода.

## Impact

- `core/runner/events.py`, `core/runner/executor.py`, `core/runner/service.py`, `core/repo.py`; тесты `tests/unit/test_runner.py`, `tests/unit/test_runner_executor.py`; CLAUDE.md (Раннер).
- Контракт с hub: новые поля необязательны, старые сообщения работают.
