# runner-consumer

## Why

Backend (hub) публикует События с вебхуков в RabbitMQ, но исполнять их некому: Python-агент сегодня работает только по HTTP-submit от пользователя. Тикеты 001/004 фиксируют целевую модель — агент становится Раннером: консьюмером очереди Событий, держащим слоты долгоживущих Экземпляров Агентов. Это отдельное усилие после карты `.wayfinder/map.md`; схема `hub.*` уже применена, пора реализовать раннер-часть.

## What Changes

- Новый пакет `core/runner/` + адаптеры: консьюмер RabbitMQ (exchange `events`, одна очередь bind `#`, auto-ack), обработка Событий `{eventId, instanceId, threadId, repositoryId, provider, action, commitSha?, ref?, dedupKey}`.
- Клейм Экземпляра: CAS `down→running (+runner_id)` в `hub.agent_instances`; Событие для Экземпляра, running на другом раннере, форвардится держателю (`POST {address}/instances/{id}/events`); дедуп по `hub.instance_events` (PK `instance_id+dedup_key`).
- Исполнение: агент поднимается из Сборки (`hub.agent_builds` → llm/sandbox connections, расшифровка `*_enc` AES-GCM-ключом из env) через существующий lead-профиль с `thread_id` из События; результат — тулзы `report_finding`→`hub.findings` и `write_report`→`hub.reports`; после обработки — `processed_at` в `instance_events`.
- Слоты: N параллельных Экземпляров (env), idle-таймаут выгрузки (`status→down`).
- HTTP API раннера (FastAPI): `POST /instances/{id}/raise|events|chat(SSE)|stop`, `GET /health`.
- Регистрация в backend `POST {backend}/api/runners` + heartbeat (`X-Runner-Token`); backend ещё пишется — клиент за портом, деградация warn+retry.
- Новая зависимость: `aio-pika`.

## Capabilities

### New Capabilities

- `runner`: Раннер — консьюмер Событий, клейм/дедуп/исполнение Экземпляров Агентов, слоты+idle, HTTP API, регистрация+heartbeat.

### Modified Capabilities

<!-- пусто: существующие капабилити (agent-graph, durable-runs, http-gateway…) не меняются; раннер — параллельный вход поверх того же lead-профиля -->

## Impact

- Код: новый `core/runner/` (домен: событие, слоты, сервис), `infra/rabbit.py` (aio-pika), `infra/db/hub_store.py` (psycopg над `hub.*`), `infra/hub/` (клиент backend), `infra/server/runner_api.py` (FastAPI-роуты раннера), точка входа раннера.
- Конфиг: новые ключи в `core/config.py` + `.env.example` (rabbit url, слоты, idle, backend url, runner token/name/address, hub enc key).
- Зависимости: `aio-pika` (новая); `cryptography`, `sse-starlette` уже в lock.
- Существующий gateway/Runtime не трогаем; `infra/sandbox/opensandbox.py` получает опциональные `domain/api_key` параметры (sandbox connection Сборки).
- Контракт с backend (сообщение События, форвард, регистрация) — backend ещё пишется; форматы фиксируются этой спекой, клиенты за портами.
