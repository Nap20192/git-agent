"""Тулинг агента, по папкам: `sandbox/` (sandbox_run, read_file), `security/`
(report_finding, load_skill, write_report + модель Находки), `delegation/` (task),
`mcp/` (тегирование + deferred-каталог tool_search). Импортируй из подпакетов —
пакет намеренно пуст, чтобы не было циклов (delegation → subagents → security).
"""
