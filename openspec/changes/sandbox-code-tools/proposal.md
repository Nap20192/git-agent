# sandbox-code-tools

## Why

У Лида и Сабагентов единственный рабочий toolset — `sandbox_run` (голый shell) и `read_file` (cat целиком, усечение по голове на 50k). Файл длиннее лимита нечитаем дальше начала, поиск по коду — ручной grep без гарантий формата, скоуп push-События (дифф коммита) недоступен из-за клона `--depth 1`, а CVE-интеллект (cve-mcp-server, `infra/mcp.py`) в раннер не подключён — `load_mcp_tools` никем не вызывается. Образ Песочницы `git-agent/sandbox:latest` (`deploy/sandbox/Dockerfile`, `task sandbox:image`) уже несёт git, ripgrep, jq, curl, python3.12+semgrep+bandit, node/npm, go+gosec, osv-scanner — тулы должны на него рассчитывать.

## What Changes

- Тулы над портом `Sandbox` (обоим — Лиду и Сабагентам): `read_file(path, offset, limit)` с номерами строк и пагинацией; `list_dir(path, depth)`; `grep_code(pattern, path, glob, context, fixed)` через `rg` с fallback на `grep -rn` (старый образ `alpine/git`); `git_diff(ref, base, path, stat)` и `git_blame(path, start_line, end_line)`.
- `browse(url, max_chars)`: читаемый текст веб-страницы (HTML → текст без скриптов/стилей/навигации, заголовок, финальный URL) для внешних фактов — advisories, CVE/NVD, документация зависимостей; исполняется в Песочнице (`python3 -c` + stdlib `urllib`/`html.parser`), только http(s), лимит размера и таймаут.
- `core/repo.py`: fetch коммита События с `--depth 2`, чтобы дифф коммита `ref^..ref` был доступен без переклона.
- Раннер подключает MCP-тулы (`load_mcp_tools()` в композиционном корне → `EventExecutor(mcp_tools=…)` → `build_lead_profile(mcp_tools=…)`): CVE-каталог через `tool_search` у Лида — как задумано спекой security-analysis.
- Промпты Лида и Сабагента перечисляют новые тулы; документация образа Песочницы по умолчанию — в CLAUDE.md.
- Установка анализаторов в тулах НЕ делается — они в образе; запуск semgrep/bandit/gosec/osv-scanner остаётся через `sandbox_run` (отдельных тулов-обёрток в этом change нет).

## Capabilities

### Modified Capabilities

- `lead-delegation`: требование «Security-инструменты агента» расширяется набором инструментов чтения/поиска/истории кода над Песочницей.
- `security-analysis`: требование «CVE-интеллект через MCP» уточняется — раннер подключает сконфигурированные MCP-серверы при старте.

## Impact

- Код: `core/tools/sandbox/` (новые модули `search.py`, `git.py`, расширенный `__init__.py`), `core/repo.py`, `core/lead/graph.py` и `core/subagents/registry.py` (промпты), `core/runner/executor.py`, `deps/container.py`.
- Тесты: герметичные, с фейковым Sandbox (`tests/unit/test_sandbox_tools.py`); правка `tests/unit/subagents/test_edge_cases.py` (распаковка списка тулов).
- Образ: тулы рассчитывают на `git-agent/sandbox:latest`; на `alpine/git` работают `read_file`/`list_dir`/`git_*`/`grep_code` (fallback grep).
