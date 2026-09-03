## REMOVED Requirements

### Requirement: Последовательный граф с состоянием
**Reason**: Pipeline-режим scan→parse→report удалён: единственный граф — лид security-ревью, исполняемый раннером по Событию.
**Migration**: Задача агенту — промпт Сборки + текст События (`core/runner/executor.py::_event_prompt`); наблюдаемость — `hub.activity` + трейсинг.

### Requirement: Запуск из CLI
**Reason**: Pipeline-режим scan→parse→report удалён: единственный граф — лид security-ревью, исполняемый раннером по Событию.
**Migration**: Задача агенту — промпт Сборки + текст События (`core/runner/executor.py::_event_prompt`); наблюдаемость — `hub.activity` + трейсинг.

### Requirement: Наблюдаемость
**Reason**: Pipeline-режим scan→parse→report удалён: единственный граф — лид security-ревью, исполняемый раннером по Событию.
**Migration**: Задача агенту — промпт Сборки + текст События (`core/runner/executor.py::_event_prompt`); наблюдаемость — `hub.activity` + трейсинг.

### Requirement: Пользовательская задача Рана
**Reason**: Pipeline-режим scan→parse→report удалён: единственный граф — лид security-ревью, исполняемый раннером по Событию.
**Migration**: Задача агенту — промпт Сборки + текст События (`core/runner/executor.py::_event_prompt`); наблюдаемость — `hub.activity` + трейсинг.

