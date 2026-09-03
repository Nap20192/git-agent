## Context

См. proposal.md. Аудит 2026-09-03: gateway и раннер не пересекаются в рантайме (общие только `core/lead`, `core/agents`, `core/subagents`, `core/middleware`, `core/tools`, `serialize`, файл `deps/container.py`); фронт (`App.tsx`) роутит только hub-экраны.

## Decisions

- **`GraphProfile` живёт в `core/lead/profile.py`**, без `PIPELINE_PROFILE` и поля `prepare` (раннер готовит репо сам в `EventExecutor`). `serialize` — в `core/runner/serialization.py`, без `values`-режима (никто не стримит `values`).
- **`core/ports.py` = только `Sandbox`.** Порты раннера — в `core/runner/ports.py`.
- **Таблицы gateway дропаются миграцией**, а не удалением старых SQL: история миграций линейна, `conftest` чистит только чекпоинты.
- **Evals: run-фаза удалена, офлайн-часть сохранена.** `run_battery.py` строил `Runtime`; пересадка на раннер — отдельный change. `evals/common.py` остаётся зеркалом констант без теста-зеркала.
- **Фронт: hub-адаптер http по умолчанию** (`VITE_HUB_URL` default `/hub`), mock — по `VITE_HUB_API=mock`. Прокси `/api → :8080` убран.

## Risks / Trade-offs

- Терять формальную модель (Lean) — осознанно: она описывала admission/lease Рана, которых больше нет.
- Спеки lead-delegation/security-analysis/memory-presets по-прежнему говорят «Ран»; читать как «ход Экземпляра по Событию». Переименование терминов — отдельный change.
