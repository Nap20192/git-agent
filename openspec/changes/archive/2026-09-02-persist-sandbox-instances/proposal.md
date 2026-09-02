## Why

Сейчас каждый Ран поднимает эфемерный OpenSandbox-сэндбокс с дефолтным TTL
(~10–30 мин) и убивает его в конце (`OpenSandboxAdapter.close()` → `kill()`).
Из-за этого прерванный Ран переживает свой сэндбокс: TTL реапит контейнер, и
последующие `run`-команды (в т.ч. при resume) бьются в мёртвый endpoint —
шторм `ConnectError: All connection attempts failed`. Живые сэндбоксы нигде не
учитываются, поэтому их нельзя ни переиспользовать, ни осознанно убрать.

## What Changes

- Сэндбоксы OpenSandbox создаются **без TTL** (`timeout=None`, manual-cleanup).
- Провиженные сэндбоксы **учитываются в БД** как Экземпляры Сэндбокса (таблица
  `sandbox_instances`): внешний id, kind/image, Ран-создатель, статус `alive|dead`,
  время создания/убийства.
- Воркер **больше не убивает** сэндбокс в конце Рана — жизненным циклом управляет
  оператор вручную (`alive` до явного kill).
- **Resume** прерванного Рана **переподключается** к его живому Экземпляру по
  `external_id` (`Sandbox.connect`, без повторного клона репозитория); если
  переподключение не удалось — Экземпляр метится `dead`, и Ран поднимает свежий.
- Появляется операция **ручного убийства** Экземпляра (`destroy()` + `status=dead`)
  и список Экземпляров — через HTTP-gateway.

## Capabilities

### New Capabilities
- `sandbox-lifecycle`: учёт живых/мёртвых Экземпляров Сэндбокса в БД, создание без
  TTL, переиспользование при resume, ручное убийство.

### Modified Capabilities
- `durable-runs`: воркер не убивает сэндбокс на завершении Рана; resume
  переподключается к живому Экземпляру вместо создания нового.
- `http-gateway`: маршруты списка Экземпляров Сэндбокса и ручного убийства.

## Impact

- `infra/opensandbox.py` — `create_sandbox(timeout=None)`, `close()` = release (не kill),
  `id`-свойство, `kill_sandbox(external_id)`.
- `core/ports.py::Sandbox` — `id`, семантика `close()` = отпустить локальные ресурсы.
- `infra/localsandbox.py` — `id=None` (локальный не учитывается/не переподключается).
- `core/runtime/worker.py` — запись Экземпляра, reconnect-по-id при resume, снятие
  auto-kill.
- `infra/sandbox_instances.py` (новый) — CRUD Экземпляров.
- `migrations/007_sandbox_instances.sql` — таблица `sandbox_instances`.
- `server/app.py` — `GET /api/sandboxes/instances`, `POST /api/sandboxes/instances/{id}/kill`.
- Тесты: `tests/unit` (учёт/выбор сэндбокса), `tests/integration` (PG-CRUD).
