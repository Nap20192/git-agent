# Proposal: add-http-gateway

## Why

Фронтенд (`frontend/`, React SPA) готов и работает на mock-адаптере; авторитетный wire-контракт уже написан — `frontend/docs/openapi.yaml`. Бэкенду не хватает HTTP-слоя: durable-рантайм Ранов доступен только из CLI. Нужен тонкий gateway, чтобы связать фронт и бек и поднять приложение целиком.

## What Changes

- Новый HTTP-gateway (FastAPI, адаптерный слой `server/`) поверх фасада `Runtime` — реализация контракта `frontend/docs/openapi.yaml`:
  - Раны: список/получение/submit (идемпотентный, с disposition)/cancel/resume/Отчёт;
  - SSE-стрим событий Рана с реплеем по курсору и явным `gap`;
  - граф Рана (топология из LangGraph `get_graph`, статусы из событий) и спецификации узлов;
  - справочники: песочницы, capabilities, Пресеты памяти;
  - сохранённые LLM-подключения (НОВАЯ таблица `connections`; ключи write-only, наружу только маска).
- Новая миграция для `connections`.
- Новые зависимости: `fastapi`, `uvicorn`.
- Redaction-инвариант: `llm_api_key` никогда не пересекает HTTP-границу.

## Capabilities

### New Capabilities

- `http-gateway`: HTTP/SSE-доступ к Ранам и справочникам системы по контракту OpenAPI; wire-схемы — `frontend/docs/openapi.yaml` (авторитетный машинный контракт, спека ссылается на него, не дублирует).

### Modified Capabilities

(нет — поведение Ранов не меняется, gateway — новый способ доступа)

## Impact

- Новый код: `server/` (FastAPI-адаптер), `migrations/` (+connections), `infra/` (стор подключений).
- `core/` не меняется: gateway зависит от фасада Runtime и портов, направление зависимостей сохранено (адаптер по краю).
- Фронтенд: переключение `VITE_API=http` (dev-прокси `/api` → бек уже настроен).
