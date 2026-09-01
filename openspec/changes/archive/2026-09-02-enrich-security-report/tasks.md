# Tasks: enrich-security-report

- [ ] 1.1 SubagentResult.findings; исполнитель собирает из хода Сабагента; report_finding — детям
- [ ] 1.2 task_terminal несёт findings; сбор Находок из событий (Лид+Сабагенты, атрибуция, дедуп, сортировка)
- [ ] 1.3 Gateway getReport: полные findings + метаданные (severity-распределение, счётчики)
- [ ] 1.4 Frontend: типы (Finding.agent, Report.meta) + красивый рендер ReportScreen
- [ ] 1.5 Тесты; task check + bun build; archive
