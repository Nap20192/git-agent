## 1. Python
- [x] 1.1 Удалить `main.py`, `core/runtime/*`, `infra/server/{app,wire,graphview}.py`, `infra/db/{run_store,connections}.py`, `infra/sandbox/{instances,localsandbox}.py`, `formal/`
- [x] 1.2 Перенести `GraphProfile` → `core/lead/profile.py`, `serialize` → `core/runner/serialization.py`; `core/ports.py` — только `Sandbox`
- [x] 1.3 Удалить pipeline (`core/agents/{graph,nodes,state}.py`), `core/tools/{tools,sync}.py`, мёртвые флаги `RuntimeFeatures`, `plan_mode`, sync-пул, `SERVER_*`, `SANDBOX_IMAGE`; `rabbit_url` → `rabbitmq_url`
- [x] 1.4 `deps/container.py` — только `runner_deps()`; `sandboxes.py` — только `connect_hub_sandbox`
- [x] 1.5 Миграция `008_drop_gateway.sql`; `tests/conftest.py` без таблиц gateway
- [x] 1.6 Удалить/поправить тесты; `run_battery.py` и `demo_subagents.py` удалены
## 2. Frontend
- [x] 2.1 Удалить `src/api/{http,client,contract,index}.ts`, `features/{runs,connections,sandboxes,reports,overview,skills}`, `hooks/{resources,useRunStream}`, primitives, `lib/{format,status,tone}`, `docs/openapi.yaml`, устаревшие docs
- [x] 2.2 Hub-адаптер http по умолчанию, `/hub` прокси; README/frontend.md
## 3. Документация и сборка
- [x] 3.1 `Taskfile.yml`: убрать `server`/`formal`, `app` = hub + раннер + фронт; `.env.example`
- [x] 3.2 `CLAUDE.md`, `CONTEXT.md` под раннер
- [x] 3.3 Спек-дельты: REMOVED durable-runs/http-gateway/post-run-chat/sandbox-lifecycle/agent-graph/repo-scan/repo-parse, MODIFIED eval-harness
