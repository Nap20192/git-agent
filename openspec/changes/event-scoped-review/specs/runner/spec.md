# runner — Delta Spec

## MODIFIED Requirements

### Requirement: Консьюмер Событий RabbitMQ

Раннер SHALL потреблять События из topic exchange `events` через одну durable-очередь с биндом `#` (competing consumers, auto-ack). Событие — JSON `{eventId, instanceId, threadId, repositoryId, provider, action, commitSha?, ref?, dedupKey}` с необязательными полями скоупа `beforeSha?` (push: состояние до пуша), `baseSha?`/`headSha?` (PR/MR), `prNumber?`, `prTitle?`, `prBody?`, `changedFiles?` (список путей). Сообщение без полей скоупа SHALL разбираться как прежде; нулевой sha провайдера SHALL трактоваться как отсутствие значения. Сообщение, не разбирающееся в Событие, SHALL логироваться и отбрасываться без падения консьюмера.

#### Scenario: Событие принято
- **WHEN** в очередь приходит валидное Событие
- **THEN** раннер начинает его обработку (клейм → дедуп → исполнение)

#### Scenario: Мусорное сообщение
- **WHEN** в очередь приходит сообщение без обязательных полей
- **THEN** раннер логирует warning и продолжает потреблять очередь

#### Scenario: Старое сообщение без полей скоупа
- **WHEN** приходит Событие только с обязательными полями и `commitSha`
- **THEN** оно разбирается, поля скоупа пусты, ход исполняется как push без `beforeSha`

### Requirement: Исполнение События Экземпляром

Раннер SHALL поднимать агента из Сборки Экземпляра: LLM — из `hub.llm_connections`, песочница — из `hub.sandbox_connections` (поля `*_enc` расшифровываются AES-GCM-ключом из env), граф — существующий lead-профиль с `thread_id` из События (чекпоинт-тред Экземпляра копит знание между Событиями). Репозиторий SHALL быть доступен в песочнице на коммите События (если задан), а коммиты скоупа (`beforeSha`, `baseSha`, `headSha`) SHALL быть догружены в клон до хода; для PR/MR раннер SHALL определить merge-base базы и головы (углубляя shallow-клон при необходимости). Задание хода SHALL зависеть от типа События: `push` — аудит ТОЛЬКО изменений `beforeSha..commitSha` (без `beforeSha` — последнего коммита с оговоркой в отчёте); `pull_request`/`merge_request` — ревью диффа `merge-base...headSha` с заголовком и описанием PR как контекстом намерения, Находками по строкам диффа, оценкой изменения attack surface и отчётом в форме PR-ревью; `manual` — изменения от предыдущего разобранного в треде коммита либо последнего коммита; `full_scan` — полный аудит репозитория. Находки агент SHALL писать тулзой `report_finding` в `hub.findings`, отчёт — тулзой `write_report` в `hub.reports`, обе привязаны к `instance_id` (и `event_id`, если есть). Ошибка исполнения SHALL оставлять запись журнала без `processed_at` (для ре-публикации backend'ом) и логироваться.

#### Scenario: Событие исполнено
- **WHEN** Событие заклеймлено и не дубль
- **THEN** агент из Сборки исполняет его в треде Экземпляра, а результаты появляются в `hub.findings`/`hub.reports`

#### Scenario: Ошибка исполнения
- **WHEN** исполнение падает с исключением
- **THEN** `processed_at` не проставляется, ошибка логируется, слот освобождается

#### Scenario: Push со скоупом
- **WHEN** приходит `push` с `beforeSha` и `commitSha`
- **THEN** задание хода требует аудита только диффа `beforeSha..commitSha`, полный репозиторий не сканируется

#### Scenario: Ревью PR
- **WHEN** приходит `pull_request` с `baseSha`, `headSha`, `prTitle`
- **THEN** merge-base доступен в песочнице, задание хода — ревью диффа с контекстом PR и отчётом-ревью

## ADDED Requirements

### Requirement: События без кода

Событие без `commitSha`/`headSha`, действие которого не `full_scan` и не `manual` (ping, issues, comments и т.п.), SHALL NOT поднимать Экземпляр и ход: раннер SHALL записать его в журнал с `processed_at` (чтобы backend не ре-публиковал) и вернуть исход `skipped_no_commit`.

#### Scenario: ping без коммита
- **WHEN** приходит Событие `ping` без `commitSha`
- **THEN** ход не исполняется, Экземпляр остаётся `down`, запись журнала имеет `processed_at`, повтор — тоже `skipped_no_commit`
