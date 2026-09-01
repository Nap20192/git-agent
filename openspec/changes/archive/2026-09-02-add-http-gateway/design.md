# Design: add-http-gateway

## Context

Фасад `Runtime` (`core/runtime/runtime.py`) уже даёт всё durable-поведение: submit/cancel/wait/subscribe/events. Фронтовый контракт зафиксирован в `frontend/docs/openapi.yaml`. Vite-прокси в dev уже шлёт `/api` на бек. Осталось написать адаптер.

## Goals / Non-Goals

- Goals: тонкий HTTP-слой по контракту; ноль новой бизнес-логики в core; secrets redaction; SSE поверх существующего `StreamBridge`.
- Non-Goals: авторизация/мультитенантность; ssh-песочницы (NotImplemented по контракту); персистентный стрим за пределами буфера (клиент дочитывает через events REST — так в контракте).

## Decisions

- **`server/` — адаптерный слой** рядом с `infra/`, а не в `core/`: зависимости направлены внутрь (server → core/infra), core не знает об HTTP.
- **Один процесс — один Runtime**, создаётся в lifespan; выбор профиля per-run невозможен в текущем фасаде (Runtime принимает один профиль) — gateway поднимает ДВА Runtime (pipeline и agent) над общим стором/бриджем? НЕТ: ponytail — один Runtime с PIPELINE_PROFILE (дефолт CLI); агентный режим через HTTP добавим отдельным change, когда фронт начнёт его слать. Ограничение зафиксировано в коде и README роутов.
- **Графовая топология — из LangGraph API**: `build_graph(...).get_graph()` → nodes/edges (не хардкод); статусы узлов — свёртка `run_events` (updates-чанки несут имя узла). Спеки узлов — из докстрингов узлов и промптов (реальные объекты, не копипаста).
- **SSE** — `StreamingResponse` поверх `Runtime.subscribe` (реплей+gap уже в бридже); терминальное закрытие по `stream_end`.
- **connections** — новая таблица (миграция NNN), ключ хранится как есть (как в runs), наружу — маска `sk-…xxxx`; check — GET `{apiBase}/models` с ключом.
- **camelCase** на проводе — ручные сериализаторы `to_wire_*` в server/ (без глобальных alias-генераторов pydantic: маппинг нетривиален — id как строки, метрики из fold-логики).

## Risks / Trade-offs

- Статусы узлов из событий — эвристика (updates-чанк = узел завершился); допустимо для UI, уточнение — через checkpoint-state позже.
- Metrics (`agentsActive/elapsedSec/tokenUsage`) считаются на лету из events — O(events) на запрос списка; кэш не нужен на текущих объёмах (ponytail).

## Open Questions

(нет — контракт зафиксирован фронтом)
