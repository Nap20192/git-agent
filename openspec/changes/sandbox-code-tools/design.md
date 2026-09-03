# sandbox-code-tools — Design

- Все тулы — замыкания над портом `Sandbox` (`build_sandbox_tools(sandbox)`), команды собираются через `shlex.quote`; ошибка команды (`SandboxCommandError`) → текст для модели, не исключение; вывод через `_clip` (`SANDBOX_OUTPUT_MAX_CHARS`).
- `grep_code`: один shell-вызов `if command -v rg …; then rg …; else grep …; fi` — код выхода поисковика сохраняется (1 = нет совпадений → «no matches», 2 = ошибка → текст). Кап по строкам вывода на стороне Python (`MAX_GREP_LINES`).
- `read_file`: `awk` (есть и в busybox) печатает диапазон с номерами строк и общее число строк в футере — модель видит, сколько осталось.
- `git_diff` без `base` — `ref^ ref`; при shallow-истории git сам скажет «unknown revision», подсказка в тексте ошибки: `git fetch --deepen`.
- MCP-тулы загружаются один раз при старте раннера (stdio-клиент `langchain-mcp-adapters` открывает сессию на вызов), только Лиду (deferred-каталог + `tool_search`); Сабагентам — нет (без изменений).
- Образ Песочницы по умолчанию: `git-agent/sandbox:latest`; `SANDBOX_IMAGE` заполняет пустой `image` sandbox-подключения на стороне hub.
