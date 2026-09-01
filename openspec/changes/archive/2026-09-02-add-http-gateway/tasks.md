# Tasks: add-http-gateway

## 1. Фундамент

- [x] 1.1 `uv add fastapi uvicorn httpx`
- [x] 1.2 Миграция: таблица `connections` (id, name, api_base, api_key, model, created_at, last_check jsonb)
- [x] 1.3 `infra/connections.py`: CRUD + check (GET {api_base}/models)

## 2. Gateway

- [x] 2.1 `server/app.py`: фабрика приложения + lifespan (store, bridge, checkpointer, Runtime)
- [x] 2.2 `server/wire.py`: сериализаторы Run/Report/Event → camelCase, маскирование ключей
- [x] 2.3 Роуты runs: list/get/submit/cancel/resume/report
- [x] 2.4 SSE `/runs/{id}/events` поверх Runtime.subscribe (реплей, gap, терминальное закрытие)
- [x] 2.5 Граф: топология из LangGraph get_graph + статусы из событий; nodespec из реальных узлов/промптов
- [x] 2.6 Справочники: sandboxes, capabilities, memory-presets, connections

## 3. Проверка

- [x] 3.1 Unit-тесты gateway (TestClient + memory-стора): redaction, disposition, SSE replay/gap, wire-формат
- [x] 3.2 `task check` зелёный
- [x] 3.3 Поднять бек (uvicorn) + фронт (bun dev, VITE_API=http), smoke: submit → стрим → отчёт
- [x] 3.4 CLAUDE.md: раздел про server/, команда запуска
