# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

git-agent — агентская система на LangChain/LangGraph для сканирования и разбора репозиториев. Python 3.13, управляется через `uv`.

Зависимости: langchain 1.x, langgraph 1.x, langfuse, langsmith, pydantic-settings.

- `core/config.py` — единая точка конфигурации: `load_dotenv()` + `Settings` (pydantic-settings), синглтон `settings`. Новые ключи добавляй туда и в `.env.example`.
- `infra/opensandbox.py` — `create_sandbox()`: песочница через OpenSandbox SDK. Сервис поднимается командой `docker compose -f deploy/docker-compose.yml up -d` (порт 8090, dev-ключ `dev-local-key`).
- `core/tracing/` — фабрика трейсинг-коллбэков (референс deerflow/tracing): `build_tracing_callbacks()` — fail-fast при включённом-но-ненастроенном провайдере, `inject_langfuse_metadata()` — session/tags на корневой трейс; env `LANGSMITH_*`/`LANGFUSE_TRACING`+ключи читаются здесь, не в Settings. Monocle не портирован (нет OTel-инструментора).
- `pkg/logger.py` — structlog: pretty в консоль, JSON по уровням в `logs/<level>.jsonl`. Бери логгер через `from pkg.logger import get_logger`.
- `core/memory/` — пресеты управления контекстом (`config.py` — класс, `prompts.py` — промпты, `presets.py` — инстансы, резолвер в `__init__.py`; `resolve_memory_preset`): явный аргумент > env `GIT_AGENT_MEMORY_PRESET` > продакшен-пресет под модель (`prod_v2`, для провайдеров вне long-context allowlist — `prod`); неизвестное имя или несовместимый провайдер — ошибка, не фолбэк. Новые конфигурации компакции добавляй пресетом сюда, не разрозненными флагами.
- `openspec/` — spec-driven разработка через OpenSpec; изменения предлагай через `/opsx:propose`.
- Postgres (порт 5433, поднимается тем же compose): таблицы `repositories`, `runs` (commit_sha + llm_api_base/key/model на каждый ран) и чекпоинты LangGraph (`PostgresSaver`). Миграции — нумерованные SQL в `migrations/`, применение: `uv run python -m migrations.migrate` (идемпотентно).
- `.env` в gitignore; шаблон — `.env.example`.

## Граф Рана

`core/agents/graph.py::build_graph(sandbox, model)` — линейный StateGraph: `scan → parse → report` (состояние `RepoState` в `state.py`, узлы в `nodes.py`). Ошибка узла кладётся в `state["error"]` и уводит граф сразу в report; песочницу создаёт и закрывает вызывающий (`main.py`). Узлы зависят от порта `core/ports.py::Sandbox` (`repo_dir`, `run`, `close`), а не от infra. Песочницы описаны в таблице `sandboxes` (kind: opensandbox/local/ssh) и создаются по имени: `infra/sandboxes.py::create_sandbox_by_name`. LLM — OpenAI-совместимый endpoint (`core/agents/llm.py::make_model`, ключи per-run через CLI-флаги или `LLM_*` в .env). Запуск: `uv run main.py <repo-url> [--model --api-base --api-key --sandbox]`. Тесты: `tests/unit` (без сервисов), `tests/integration` (Postgres), `tests/e2e` (OpenSandbox); `task test:unit` и т.д..

## Runtime (core/runtime/)

Durable-исполнение Ранов по образцу deer-flow: «ран — это ресурс, а не запрос». `Runtime.submit()` идемпотентен: admission — атомарный `claim` CAS на строке `runs` (unique `(repository_id, commit_sha, llm_model)`); упавший ран при resubmit возобновляется с чекпоинта под тем же id. Lease+heartbeat с fail-closed fence (`ownership_lost` ⇒ ноль durable-записей, но `publish_end` всегда), orphan recovery через `claim_for_takeover` (истечение lease перепроверяется в момент записи), отмена — `cancel_requested_at`-мейлбокс, читаемый при продлении lease. Стрим — `MemoryStreamBridge`: реплей по курсору O(1), честный `StreamGap` при выпадении из буфера. Терминальные статусы неперезаписываемы; финализация воркера отменоустойчива (shield-loop). Порты `RunStore`/`StreamBridge` — в `core/ports.py`, PG-адаптер — `infra/run_store.py`, memory-варианты — исполняемая спецификация (`tests/unit/test_runtime.py`; PG-порт-тесты — `tests/integration/test_run_store_pg.py`). Формальная модель инвариантов — `formal/RuntimeCore.lean` (Lean 4). Доказательства проверяются **в pytest** (`tests/unit/test_formal.py` шеллит `lean`, требует exit 0 + ноль `sorry`; скип без lean), так что `task test`/`task check` их верифицируют; `task formal` — отдельно. lean — в `~/.elan/bin` (не в PATH по умолчанию). Карта портирования — `formal/MAPPING.md`; статусная машина `LEGAL_TRANSITIONS`+`assert_transition` в `schemas.py`, зеркала теорем — `tests/unit/test_invariants.py`. Меняешь семантику переходов/admission — сначала обнови модель (тесты должны пройти) и карту.

Термины проекта — в `CONTEXT.md` (глоссарий); используй их в коде и обсуждениях.

## Архитектура

Пишем по гексагональной архитектуре (ports & adapters): `core/` — домен и прикладная логика (конфиг, пресеты памяти `core/memory/`, агент — `core/agents/`: состояние, фабрика `build_agent`, middleware фич в `core/agents/middleware/` (есть `HistoryMiddleware(run_id)` — полная история рана в таблицу `run_events`), далее узлы/граф), не зависит от способа запуска; адаптеры к внешнему миру — по краям (`infra/` — клиенты внешних систем, `infra/postgres.py` — пул psycopg + операции repositories/runs; `migrations/` — схема БД, `deploy/` — инфраструктура, `main.py` — CLI). Зависимости направлены внутрь: core не импортирует из main и адаптеров.

## Commands

Основной путь — Taskfile (`task --list`): `task up`/`down` (инфраструктура), `task migrate`, `task lint`/`fix`/`fmt` (ruff, конфиг в pyproject.toml), `task test` (pytest, включая Lean-верификацию), `task check` (lint+test), `task run -- <repo-url>`. Напрямую: `uv add <package>` — зависимости (pyproject.toml руками не редактировать), `uv sync` — окружение.

## Notes

- LangChain 1.x API сильно изменился — не полагайся на память, сверяйся с актуальной документацией LangChain/LangGraph (в сессии доступен MCP-сервер docs-langchain и скилл langchain-docs).
