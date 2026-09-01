# Proposal: improve-lead-observability

## Why

Три пробела в UI: (1) Раны нельзя удалить — список копится мусором; (2) граф агентного Рана почти пуст, если Лид не делегировал; (3) стрим событий агентного Рана показывает сырые имена узлов LangGraph (model, middleware) вместо рассуждений и вызовов инструментов Лида. Наблюдаемость Лида хуже, чем у сабагентов, хотя данные уже в событиях.

## What Changes

- **Удаление Рана**: DELETE по Рану (чекпоинты + run_events + строка), запрет на активный Ран (сначала отмена); кнопка в UI.
- **Стрим Лида**: события `updates` агентного Рана разворачиваются в читаемые шаги — рассуждение Лида, его вызовы инструментов (sandbox_run/read_file/load_skill/report_finding/task) и результаты; служебные узлы middleware отбрасываются.
- **Граф Лида**: узел Лида несёт активность (число вызовов инструментов, Находок); дети-Сабагенты — с живым статусом и токенами.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `http-gateway`: удаление Рана; обогащённый стрим и граф агентного Рана.

## Impact

- `infra/run_store.py` (+delete), `server/app.py` (DELETE-роут, event_to_wire skip), `server/wire.py` (разбор lead-updates), `server/graphview.py` (активность Лида), `frontend` (api.deleteRun, кнопка, describe() для agent_step).
