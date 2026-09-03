# findings-v2-blame — Tasks

- [x] 1.1 Модель Находки v2 (`findings.py`): category/confidence/references, lineStart/lineEnd, blame-поля, обязательный file
- [x] 1.2 `report_finding`: новые аргументы, валидация, подсказка «blame не передавай»
- [x] 1.3 `blame.py`: парсер porcelain (доминирующий коммит), `BlameResolver` с кэшем и introducedBy по merge-base --is-ancestor
- [x] 1.4 `report.py`: `WriteReportArgs`, сборка структуры, markdown-рендер с таблицей
- [x] 1.5 `hub.py`: blame при персисте, structured в add_report; `executor.scope_range`; `hub_store` колонки v2
- [x] 2.1 Промпты Лида/Сабагента; CLAUDE.md
- [x] 3.1 Тесты: porcelain, in/out диапазона, кэш, рендер, структурированный отчёт
