## REMOVED Requirements

### Requirement: Ран — ресурс, а не запрос
**Reason**: Ран как durable-ресурс (admission/lease/fence/терминальные статусы) заменён Экземпляром Агента: надзор за раннерами и ре-публикацию Событий ведёт hub, гарантии дают дедуп-журнал `hub.processed_events` и чекпоинты.
**Migration**: См. `openspec/specs/runner`; статусы Экземпляра `down|running`, cancel хода — `POST /instances/{id}/stop`, стрим — `activity` SSE.

### Requirement: Терминальность статусов
**Reason**: Ран как durable-ресурс (admission/lease/fence/терминальные статусы) заменён Экземпляром Агента: надзор за раннерами и ре-публикацию Событий ведёт hub, гарантии дают дедуп-журнал `hub.processed_events` и чекпоинты.
**Migration**: См. `openspec/specs/runner`; статусы Экземпляра `down|running`, cancel хода — `POST /instances/{id}/stop`, стрим — `activity` SSE.

### Requirement: Владение исполнением и восстановление сирот
**Reason**: Ран как durable-ресурс (admission/lease/fence/терминальные статусы) заменён Экземпляром Агента: надзор за раннерами и ре-публикацию Событий ведёт hub, гарантии дают дедуп-журнал `hub.processed_events` и чекпоинты.
**Migration**: См. `openspec/specs/runner`; статусы Экземпляра `down|running`, cancel хода — `POST /instances/{id}/stop`, стрим — `activity` SSE.

### Requirement: Отмена
**Reason**: Ран как durable-ресурс (admission/lease/fence/терминальные статусы) заменён Экземпляром Агента: надзор за раннерами и ре-публикацию Событий ведёт hub, гарантии дают дедуп-журнал `hub.processed_events` и чекпоинты.
**Migration**: См. `openspec/specs/runner`; статусы Экземпляра `down|running`, cancel хода — `POST /instances/{id}/stop`, стрим — `activity` SSE.

### Requirement: Наблюдаемый стрим событий
**Reason**: Ран как durable-ресурс (admission/lease/fence/терминальные статусы) заменён Экземпляром Агента: надзор за раннерами и ре-публикацию Событий ведёт hub, гарантии дают дедуп-журнал `hub.processed_events` и чекпоинты.
**Migration**: См. `openspec/specs/runner`; статусы Экземпляра `down|running`, cancel хода — `POST /instances/{id}/stop`, стрим — `activity` SSE.

### Requirement: Учёт расхода LLM
**Reason**: Ран как durable-ресурс (admission/lease/fence/терминальные статусы) заменён Экземпляром Агента: надзор за раннерами и ре-публикацию Событий ведёт hub, гарантии дают дедуп-журнал `hub.processed_events` и чекпоинты.
**Migration**: См. `openspec/specs/runner`; статусы Экземпляра `down|running`, cancel хода — `POST /instances/{id}/stop`, стрим — `activity` SSE.

### Requirement: Переиспользование Сэндбокса при Возобновлении
**Reason**: Ран как durable-ресурс (admission/lease/fence/терминальные статусы) заменён Экземпляром Агента: надзор за раннерами и ре-публикацию Событий ведёт hub, гарантии дают дедуп-журнал `hub.processed_events` и чекпоинты.
**Migration**: См. `openspec/specs/runner`; статусы Экземпляра `down|running`, cancel хода — `POST /instances/{id}/stop`, стрим — `activity` SSE.

