# runner-consumer — Tasks

## 1. Основа

- [x] 1.1 Добавить `aio-pika` (и `cryptography` в прямые зависимости) через `uv add`
- [x] 1.2 Новые ключи в `core/config.py` + `.env.example`: `RABBIT_URL`, `RUNNER_NAME`, `RUNNER_ADDRESS`, `RUNNER_PORT`, `RUNNER_SLOTS`, `RUNNER_IDLE_TIMEOUT_SECONDS`, `RUNNER_TOKEN`, `BACKEND_URL`, `HUB_ENC_KEY`
- [x] 1.3 `core/runner/events.py`: датакласс/парсер События (camelCase JSON → Event), `core/runner/ports.py`: `InstanceStore`, `HubClient`

## 2. Домен раннера

- [x] 2.1 `core/runner/service.py`: RunnerService — слоты (Semaphore + dict Экземпляров), handle_event (клейм CAS → локально/форвард → дедуп → исполнение → processed_at), raise/stop/chat, idle-цикл
- [x] 2.2 `core/runner/executor.py`: подъём агента из Сборки (расшифровка ключей, make_model, sandbox из connection, prepare_repo на commitSha, lead-профиль с thread_id, hub-тулзы report_finding/write_report)
- [x] 2.3 `core/runner/crypto.py`: AES-GCM decrypt (`nonce||ct`, ключ base64 из env)

## 3. Адаптеры

- [x] 3.1 `infra/db/hub_store.py`: psycopg над `hub.*` — claim/release CAS, дедуп-журнал, load instance+build+connections+repository, insert findings/reports, sandbox_instances link, адрес раннера-держателя
- [x] 3.2 `infra/rabbit.py`: aio-pika консьюмер (exchange `events`, очередь bind `#`, auto-ack, warn на мусор)
- [x] 3.3 `infra/hub_client.py`: httpx — register/heartbeat (X-Runner-Token, warn+retry), форвард События держателю
- [x] 3.4 `infra/sandbox/opensandbox.py`: опциональные `domain`/`api_key` в `create_sandbox`/`connect_sandbox`

## 4. HTTP API и точка входа

- [x] 4.1 `infra/server/runner_api.py`: FastAPI-роуты `POST /instances/{id}/raise|events|chat|stop`, `GET /health`; chat — SSE
- [x] 4.2 `runner.py`: `create_runner_app()` — lifespan (чекпоинтер, консьюмер, heartbeat, idle-цикл, graceful shutdown)

## 5. Тесты и проверка

- [x] 5.1 `tests/unit/runner/` — герметично: парсер События, клейм/форвард/дедуп-логика сервиса с fake-портами, idle-выгрузка, crypto roundtrip
- [x] 5.2 `task check` зелёный; коммит в `wt/agent`
