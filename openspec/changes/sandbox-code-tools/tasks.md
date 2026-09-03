# sandbox-code-tools — Tasks

## 1. Тулы над Sandbox
- [x] 1.1 `read_file(path, offset, limit)` с номерами строк и футером «lines a–b of N»; `list_dir(path, depth)`
- [x] 1.2 `core/tools/sandbox/search.py`: `grep_code` через rg с fallback на grep
- [x] 1.3 `core/tools/sandbox/git.py`: `git_diff`, `git_blame`
- [x] 1.5 `core/tools/sandbox/browse.py` + `html_text.py`: browse через python3 в Песочнице, промпты «browse — для внешних фактов»
- [x] 1.4 `core/repo.py`: `--depth 2` при fetch коммита События

## 2. Wiring
- [x] 2.1 `deps/container.py` → `load_mcp_tools()` → `EventExecutor(mcp_tools)` → `build_lead_profile(mcp_tools=…)`
- [x] 2.2 Промпты: `LEAD_SYSTEM_PROMPT`, `_GENERAL_PURPOSE_PROMPT`/description
- [x] 2.3 CLAUDE.md: образ `git-agent/sandbox:latest`, состав, где Dockerfile

## 3. Тесты
- [x] 3.1 `tests/unit/test_sandbox_tools.py` (фейковый Sandbox: команды, клип, ошибки текстом, no-matches, fallback)
- [x] 3.2 Правка `test_edge_cases.py::test_sandbox_tools_clip_and_error_text`; тест прокидки `mcp_tools` в executor
