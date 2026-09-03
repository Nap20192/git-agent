## REMOVED Requirements

### Requirement: Экземпляр Сэндбокса без TTL
**Reason**: Жизненным циклом Экземпляров Сэндбокса владеет hub (`hub.sandbox_instances`, `POST/DELETE /api/sandbox-instances`); раннер только подключается.
**Migration**: Учёт и kill — в Go (`backend/internal/hub/adapters/httpapi/sandboxes.go`), контракт — `backend/docs/openapi.yaml`.

### Requirement: Учёт живых и мёртвых Экземпляров
**Reason**: Жизненным циклом Экземпляров Сэндбокса владеет hub (`hub.sandbox_instances`, `POST/DELETE /api/sandbox-instances`); раннер только подключается.
**Migration**: Учёт и kill — в Go (`backend/internal/hub/adapters/httpapi/sandboxes.go`), контракт — `backend/docs/openapi.yaml`.

### Requirement: Ручное убийство Экземпляра
**Reason**: Жизненным циклом Экземпляров Сэндбокса владеет hub (`hub.sandbox_instances`, `POST/DELETE /api/sandbox-instances`); раннер только подключается.
**Migration**: Учёт и kill — в Go (`backend/internal/hub/adapters/httpapi/sandboxes.go`), контракт — `backend/docs/openapi.yaml`.

