# findings-v2-blame

## Why

Находка несла severity/CWE/CVE/файл/строки/evidence/remediation, а title/description/impact/confidence паковались в `evidence` текстом — hub и UI не могли ни фильтровать, ни показывать структурно. Отчёт был одним `summary`-текстом без скоупа, метода и таблицы Находок. Кто и когда внёс уязвимые строки (git blame) и внесены ли они текущим Событием — ключевой контекст для ревью, которого не было вовсе. Hub параллельно добавляет колонки (миграция 007).

## What Changes

- Находка v2 (camelCase на проводе): title, description, impact, confidence (high|medium|low), category (injection|auth|crypto|secrets|deps|config|xss|ssrf|path|logic|other), severity/cwe/cve/file/lineStart/lineEnd/evidence/remediation, references ([url]); обязательны title/severity/file. Blame — blameAuthor/blameEmail/blameCommit/blameDate(ISO)/blameCommitMessage и introducedBy (this_event|earlier) — заполняет РАННЕР по `git blame --porcelain` в Песочнице и ancestry относительно диапазона События; модель blame не передаёт, конфликт → инструмент.
- `write_report` принимает структуру {summary, scope{eventType, range, filesTouched, linesChanged}, method[], topRisks[], recommendations[], limitations[]}; система добавляет findingsBySeverity и Находки хода; персист в `hub.reports.structured` (jsonb) + markdown-рендер (заголовки, списки, таблица `severity | title | file:lines | blame author @ date | cwe | confidence`) в `summary` для старого UI.
- Промпты Лида/Сабагентов требуют полные поля Находки; blame не просят.

## Capabilities

### Modified Capabilities

- `security-analysis`: «Структурированные Находки» расширяется полями v2 и blame; добавляется требование о структурированном Отчёте.

## Impact

- `core/tools/security/{findings,report_finding,blame,report,hub}.py`, `core/runner/{ports,executor}.py`, `infra/db/hub_store.py`, промпты; тесты `tests/unit/test_findings_v2.py` и правки существующих.
- Контракт с hub (миграция 007): `hub.findings` — title, description, impact, confidence, category, "references" (jsonb), blame_author, blame_email, blame_commit, blame_date, blame_commit_message, introduced_by; `hub.reports.structured` (jsonb). `evidence` продолжает дублировать title/description/impact для UI на старых колонках.
