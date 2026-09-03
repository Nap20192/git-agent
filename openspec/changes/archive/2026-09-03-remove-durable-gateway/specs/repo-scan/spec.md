## REMOVED Requirements

### Requirement: Клонирование репозитория в песочнице
**Reason**: Pipeline-режим scan→parse→report удалён: единственный граф — лид security-ревью, исполняемый раннером по Событию.
**Migration**: Клон/checkout — `core/repo.py::prepare_repo` внутри хода Экземпляра; структуру лид смотрит sandbox-тулами.

### Requirement: Сканирование структуры
**Reason**: Pipeline-режим scan→parse→report удалён: единственный граф — лид security-ревью, исполняемый раннером по Событию.
**Migration**: Клон/checkout — `core/repo.py::prepare_repo` внутри хода Экземпляра; структуру лид смотрит sandbox-тулами.

