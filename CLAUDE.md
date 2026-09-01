# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

git-agent — агентская система на LangChain/LangGraph для сканирования и разбора репозиториев. Python 3.13, управляется через `uv`.

Зависимости: langchain 1.x, langgraph 1.x, langfuse, langsmith, pydantic-settings.

- `core/config.py` — единая точка конфигурации: `load_dotenv()` + `Settings` (pydantic-settings), синглтон `settings`. Новые ключи добавляй туда и в `.env.example`.
- `infra/opensandbox.py` — `create_sandbox()`: песочница через OpenSandbox SDK. Сервис поднимается командой `docker compose -f deploy/docker-compose.yml up -d` (порт 8090, dev-ключ `dev-local-key`).
- `pkg/logger.py` — structlog: pretty в консоль, JSON по уровням в `logs/<level>.jsonl`. Бери логгер через `from pkg.logger import get_logger`.
- `core/memory/` — пресеты управления контекстом (`config.py` — класс, `prompts.py` — промпты, `presets.py` — инстансы, резолвер в `__init__.py`; `resolve_memory_preset`): явный аргумент > env `GIT_AGENT_MEMORY_PRESET` > продакшен-пресет под модель (`prod_v2`, для провайдеров вне long-context allowlist — `prod`); неизвестное имя или несовместимый провайдер — ошибка, не фолбэк. Новые конфигурации компакции добавляй пресетом сюда, не разрозненными флагами.
- `openspec/` — spec-driven разработка через OpenSpec; изменения предлагай через `/opsx:propose`.
- Postgres (порт 5433, поднимается тем же compose): таблицы `repositories`, `runs` (commit_sha + llm_api_base/key/model на каждый ран) и чекпоинты LangGraph (`PostgresSaver`). Миграции — нумерованные SQL в `migrations/`, применение: `uv run python -m migrations.migrate` (идемпотентно).
- `.env` в gitignore; шаблон — `.env.example`.

## Граф Рана

`core/agents/graph.py::build_graph(sandbox, model)` — линейный StateGraph: `scan → parse → report` (состояние `RepoState` в `state.py`, узлы в `nodes.py`). Ошибка узла кладётся в `state["error"]` и уводит граф сразу в report; песочницу создаёт и закрывает вызывающий (`main.py`). Узлы зависят от порта `core/ports.py::Sandbox` (`repo_dir`, `run`, `close`), а не от infra. Песочницы описаны в таблице `sandboxes` (kind: opensandbox/local/ssh) и создаются по имени: `infra/sandboxes.py::create_sandbox_by_name`. LLM — OpenAI-совместимый endpoint (`core/agents/llm.py::make_model`, ключи per-run через CLI-флаги или `LLM_*` в .env). Запуск: `uv run main.py <repo-url> [--model --api-base --api-key --sandbox]`. Smoke-тест: `uv run pytest` (нужен запущенный OpenSandbox).

Термины проекта — в `CONTEXT.md` (глоссарий); используй их в коде и обсуждениях.

## Архитектура

Пишем по гексагональной архитектуре (ports & adapters): `core/` — домен и прикладная логика (конфиг, пресеты памяти `core/memory/`, агент — `core/agents/`: состояние, фабрика `build_agent`, middleware фич в `core/agents/middleware/` (есть `HistoryMiddleware(run_id)` — полная история рана в таблицу `run_events`), далее узлы/граф), не зависит от способа запуска; адаптеры к внешнему миру — по краям (`infra/` — клиенты внешних систем, `infra/postgres.py` — пул psycopg + операции repositories/runs; `migrations/` — схема БД, `deploy/` — инфраструктура, `main.py` — CLI). Зависимости направлены внутрь: core не импортирует из main и адаптеров.

## Commands

- `uv run main.py` — запуск
- `uv add <package>` — добавить зависимость (не редактируй pyproject.toml вручную)
- `uv sync` — установить окружение из lock-файла

Тестов и линтера пока нет; при добавлении используй `uv run pytest` / `uv run ruff check`.

## Notes

- LangChain 1.x API сильно изменился — не полагайся на память, сверяйся с актуальной документацией LangChain/LangGraph (в сессии доступен MCP-сервер docs-langchain и скилл langchain-docs).
