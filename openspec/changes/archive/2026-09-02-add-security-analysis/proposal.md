# Proposal: add-security-analysis

## Why

git-agent разбирает репозиторий, но выдаёт только описательный Отчёт. UI («Vulnhunt») и направление проекта — про безопасность. Референс strix даёт зрелую модель: находки с severity/CWE/CVE/PoC/remediation, security-промпт агента и загружаемые skills. Плюс есть внешний CVE-интеллект (cve-mcp-server) — его подключаем как MCP. Итог: git-agent в агентном режиме проводит security-ревью кода и выдаёт структурированные Находки.

## What Changes

- **Модель Находки (Finding)**: severity, класс (CWE), CVE, файл/строки, описание, impact, evidence, confidence, remediation — по образцу strix (адаптировано под статический анализ кода в песочнице; live-тестирование не портируется).
- **Инструмент `report_finding`**: Лид/Сабагенты фиксируют Находки; Отчёт агентного Рана = список Находок + резюме.
- **Security-промпт Лида**: реврайт в agent-режиме — авторизованное security-ревью кода репозитория.
- **Skills**: `core/skills/` — markdown-скиллы (курированный код-релевантный поднабор из strix: SQLi, XSS, RCE, path traversal, SSRF, IDOR, deser, secrets, JWT, …) + загрузчик + тул `load_skill` (инъекция справки в ход, максимум N).
- **CVE MCP**: cve-mcp-server подключается как MCP-сервер через уже существующий deferred-каталог (`core/tools/`); тулы уезжают за `tool_search`, Лид тянет их по мере надобности. Сервер недоступен ⇒ предупреждение, Ран продолжается.

## Capabilities

### New Capabilities

- `security-analysis`: агентное security-ревью кода репозитория — Находки (severity/CWE/CVE/evidence/remediation), skills-справочник, CVE-интеллект через MCP.

### Modified Capabilities

- `lead-delegation`: у Лида/Сабагентов появляются security-тулы (report_finding, load_skill) и MCP-тулы; системный промпт агент-режима — security-ревью.

## Impact

- Новое: `core/skills/` (+markdown), `core/agents/findings.py` (модель + тул), MCP-конфиг и загрузка.
- Меняется: `core/lead/graph.py` (промпт, тулы, extract_report), `server/wire.py` + `frontend` (Находки в Отчёте), `core/tools` wiring в лид.
- Зависимость: `langchain-mcp-adapters`. cve-mcp-server — внешний процесс (stdio), не вендорится; путь/команда — в конфиге.
- Скоуп: только статический анализ склонированного кода. Live-тулы strix (browser/proxy/exploit) не портируются.
