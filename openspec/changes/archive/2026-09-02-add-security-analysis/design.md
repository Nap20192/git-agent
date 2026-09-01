# Design: add-security-analysis

## Context

Лид — ReAct-агент (`build_agent`), Отчёт извлекается из финального сообщения. Deferred-MCP-каталог уже есть (`core/tools/`). Песочница даёт статический доступ к склонированному коду. strix — референс модели Находки, промпта и skills; его live-тулинг (browser/proxy/exploit) вне скоупа.

## Decisions

- **Находки — из истории сообщений, без кастомного state.** Тул `report_finding` валидирует и подтверждает; `_lead_report` собирает Находки из `tool_calls` с именем `report_finding` в `messages` (per-run state, без коллектора и утечки между Ранами в долгоживущем gateway).
- **Skills — markdown с frontmatter** (`core/skills/<category>/<name>.md`), загрузчик резолвит по имени, `load_skill` инъектирует тело как tool-результат (не меняет промпт). Курируем код-релевантный поднабор strix.
- **CVE MCP — через существующий `assemble_deferred_tools`.** Клиент (`langchain-mcp-adapters` `MultiServerMCPClient`) поднимается один раз (CLI/gateway), тулы тегируются и уезжают за `tool_search`; имена — в промпт. Список серверов — в конфиге; недоступность → warn+continue (fail-open для доступности, в отличие от fail-closed бинда схем).
- **Режим security-ревью = agent-режим** с новым промптом; pipeline не трогаем.

## Risks / Trade-offs

- Модель может не звать `report_finding` — тогда Находок нет, но резюме есть (не ошибка).
- cve-mcp — внешний процесс со своими зависимостями; запуск через `uv run --project`. Флейки изолированы warn-ветвью.

## Open Questions

(нет)
