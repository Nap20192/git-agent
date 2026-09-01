# Design: add-repo-scan-agent

## Context

Инфраструктура уже есть: `core/config.py` (pydantic-settings + .env), `infra/opensandbox.py` (`create_sandbox()`), `pkg/logger.py` (structlog), OpenSandbox в `deploy/docker-compose.yml` (порт 8090). LangChain/LangGraph 1.x установлены. Мотивация — см. proposal.md.

## Goals / Non-Goals

**Goals:**
- Минимальный рабочий линейный граф scan → parse → report на LangGraph.
- Все git-операции и чтение недоверенных файлов — внутри одной песочницы на прогон.
- Наблюдаемость из коробки: structlog-логи каждого узла, LangSmith по env, Langfuse через CallbackHandler.

**Non-Goals:**
- Параллельный разбор нескольких репозиториев, чекпоинты/резюмирование графа, human-in-the-loop.
- Глубокий AST-анализ всех языков — стартуем с Python + LLM-описание для остального.
- Веб-интерфейс/API — только CLI.

## Decisions

- **Структура**: новый пакет `core/agents/` (`state.py`, `nodes.py`, `graph.py`); `main.py` — тонкий CLI (argparse). Alternative: всё в main.py — отклонено, узлы будут расти.
- **Состояние**: один `TypedDict` (`RepoState`: repo_url, scan-результат, parse-результат, report, error). Alternative: pydantic-модели на каждый узел — избыточно сейчас.
- **Песочница**: одна на прогон, создаётся до графа, кладётся в состояние/контекст, всегда `kill()` в finally. Команды в песочнице: `git clone`, `find`/`wc`-подобные обходы; на хост возвращается только текст.
- **Разбор Python**: `ast` из stdlib по содержимому файлов, вычитанных из песочницы (файлы читаются как текст — код не исполняется). Alternative: tree-sitter — добавим при мультиязычности.
- **LLM**: `init_chat_model` из langchain — провайдер задаётся конфигом, без жёсткой привязки. Langfuse `CallbackHandler` передаётся в вызовы модели; LangSmith включается сам по `LANGSMITH_*` env.
- **Отчёт**: dict → печать JSON в stdout. Alternative: markdown-рендер — позже.

## Risks / Trade-offs

- [Таймаут SDK 30с при первом pull образа песочницы] → увеличить `request_timeout` в `ConnectionConfig` либо прогреть образ в deploy.
- [Большие репозитории раздуют контекст LLM] → лимит на число/размер файлов, передавать LLM только сводки, а не сырцы целиком.
- [Чтение файлов из песочницы по одному — медленно] → tar-архив одним заходом; оптимизировать после первого рабочего прогона.

## Open Questions

- Какой провайдер LLM по умолчанию (anthropic/openai) — решится при появлении ключа в .env.
