# Proposal: add-run-limits

## Why

Форма нового Рана уже собирает лимиты (токен-бюджет, максимум Сабагентов, флаги subagent/loop_detection), но бэкенд их игнорирует — они не доходят до агента. И нет способа продолжить Ран с поднятым лимитом, когда он упёрся в бюджет (token_capped/turn_capped).

## What Changes

- **Лимиты Рана**: токен-бюджет, максимум одновременных Сабагентов, включение делегирования и loop-detection задаются при запуске и применяются к агенту. Лимиты хранятся на Ране (переживают Возобновление).
- **Продолжение Рана**: Возобновление принимает опционально новые лимиты — можно поднять бюджет и продолжить упавший/упёршийся Ран с Чекпоинта.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `http-gateway`: submit принимает лимиты Рана; resume принимает опционально новые лимиты (продолжение с поднятым бюджетом).
- `lead-delegation`: лимиты (token budget, capacity, флаги) конфигурируются на Ран, а не захардкожены.

## Impact

- Миграция `runs.limits JSONB`; `infra/run_store.py` (+set_limits), `core/runtime/{runtime,worker}.py` (проброс), `core/runtime/profile.py` + `core/lead/graph.py` (build с лимитами), `server/app.py` (submit/resume), `frontend` (форма уже есть; продолжение с лимитом).
