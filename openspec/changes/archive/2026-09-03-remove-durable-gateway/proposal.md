## Why

В `agent/` жили два непересекающихся мира: durable-gateway (`main.py`, `core/runtime`, FastAPI над Ранами, Lean-модель, pipeline scan→parse→report) и раннер под hub (`runner.py`, `core/runner`, RabbitMQ, `hub.*`). После разбиения монорепы все коммиты шли только в раннер, фронт роутит только hub-экраны, а `task app` поднимал мёртвый gateway. Ран как ресурс (admission/lease/fence/терминальные статусы) заменён Экземпляром Агента: надзор за раннерами и ре-публикацию Событий забрал hub, гарантии дают дедуп-журнал и чекпоинты.

## What Changes

- **BREAKING** Удалён durable-gateway целиком: `main.py`, `core/runtime/*` (кроме `GraphProfile` → `core/lead/profile.py` и `serialize` → `core/runner/serialization.py`), `infra/server/{app,wire,graphview}.py`, `infra/db/{run_store,connections}.py`, `infra/sandbox/{instances,localsandbox}.py`, `formal/` (Lean), таблицы `repositories/runs/run_events/connections/sandboxes/sandbox_instances` (миграция `008_drop_gateway.sql`).
- **BREAKING** Удалён pipeline-режим (`core/agents/{graph,nodes,state}.py`): единственный граф — лид security-ревью.
- Удалены мёртвые модули и флаги: `core/tools/{tools,sync}.py`, флаги `RuntimeFeatures` без middleware (`memory/vision/auto_title/guardrail`), `plan_mode`, sync-пул psycopg, `SERVER_*`/`SANDBOX_IMAGE`; `RABBIT_URL` объединён с `RABBITMQ_URL` hub'а.
- Фаза платного прогона evals (`run_battery.py`) удалена (строила `Runtime`); офлайн-грейд, батарея и их тесты сохранены.
- Фронт: удалены адаптер и экраны gateway (`src/api/{http,client,contract,index}.ts`, `features/{runs,connections,sandboxes,reports,overview,skills}`, primitives, `docs/openapi.yaml`); hub-адаптер по умолчанию http через `/hub`.
- Спеки durable-runs, http-gateway, post-run-chat, sandbox-lifecycle, agent-graph, repo-scan, repo-parse — удалены; eval-harness — платная фаза помечена как переносимая на раннер.

## Capabilities

### Modified Capabilities
- `eval-harness`: фаза платного прогона больше не привязана к durable-gateway.

### Removed Capabilities
- `durable-runs`, `http-gateway`, `post-run-chat`, `sandbox-lifecycle` — реализуются hub'ом (Go) и раннером по спеке `runner`.
- `agent-graph`, `repo-scan`, `repo-parse` — pipeline-режим удалён.

## Impact

`agent/`: −~4000 строк, тесты `test_runtime/test_gateway/test_chat/test_invariants/test_formal/test_sandbox_provision/test_run_store_pg/test_sandbox_instances_pg/e2e test_agent` удалены; unit 173 / integration 17 зелёные. `frontend/`: typecheck и build чистые. `Taskfile`: `task server`/`task formal` удалены, `task app` поднимает hub + раннер + фронт. `CLAUDE.md`, `CONTEXT.md` переписаны под раннер.
