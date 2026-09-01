# Tasks: add-security-analysis

## 1. Skills
- [x] 1.1 core/skills/ + курированные markdown-скиллы (vuln-класс, код-релевантные)
- [x] 1.2 Загрузчик: list/validate/load; парсинг frontmatter
- [x] 1.3 Тул load_skill (LangChain), лимит на число

## 2. Находки
- [x] 2.1 Модель Finding + тул report_finding
- [x] 2.2 _lead_report собирает Находки из tool_calls; Отчёт = {summary, findings}
- [x] 2.3 Security-промпт Лида (agent-режим)

## 3. CVE MCP
- [x] 3.1 langchain-mcp-adapters; загрузка MCP-тулов (конфиг серверов; warn при недоступности)
- [x] 3.2 assemble_deferred_tools в build_lead_profile; имена в промпт

## 4. Наружу
- [x] 4.1 server/wire.py: findings в Отчёте; contract.ts Finding
- [x] 4.2 UI: рендер Находок
- [x] 4.3 Тесты (skills loader, report_finding→_lead_report, wire findings, MCP warn); task check + bun build; archive
