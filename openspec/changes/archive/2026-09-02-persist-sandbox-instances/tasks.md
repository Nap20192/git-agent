## 1. Схема БД

- [x] 1.1 `migrations/007_sandbox_instances.sql`: таблица `sandbox_instances`
  (id, external_id UNIQUE, kind, image, run_id BIGINT REFERENCES runs(id),
  status TEXT CHECK IN ('alive','dead') DEFAULT 'alive', created_at, killed_at)
- [x] 1.2 Применить миграцию (`uv run python -m migrations.migrate`, идемпотентно)

## 2. Порт и адаптеры сэндбокса

- [x] 2.1 `core/ports.py::Sandbox`: добавить `id: str | None`; уточнить докстринг
  `close()` = «отпустить локальные ресурсы, не убивать remote»
- [x] 2.2 `infra/opensandbox.py`: `create_sandbox(image, timeout=None)` (без TTL);
  `close()` → `self._sandbox.close()` (release, не kill); свойство `id`
- [x] 2.3 `infra/opensandbox.py::connect_sandbox(external_id)` — адаптер поверх
  `Sandbox.connect(id, skip_health_check=True)`
- [x] 2.4 `infra/localsandbox.py`: свойство `id` → `None` (close() без изменений)

## 3. CRUD Экземпляров

- [x] 3.1 `infra/sandbox_instances.py`: `record_instance(external_id, kind, image, run_id)`,
  `alive_instance_for_run(run_id)`, `list_instances()`, `mark_dead(instance_id|external_id)`
- [x] 3.2 `infra/sandbox_instances.py::kill_sandbox(instance_id)`:
  connect→destroy→mark_dead; идемпотентно для уже `dead`

## 4. Воркер: create-vs-connect, без auto-kill

- [x] 4.1 Воркер: при resume+живой Экземпляр Рана → `connect_sandbox(external_id)`,
  без повторного `prepare`; иначе `create_sandbox(timeout=None)` + `record_instance` +
  `prepare`
- [x] 4.2 Неудачный reconnect → `mark_dead(старый)` + fallback на create+prepare
- [x] 4.3 Финализация: `sandbox.close()` теперь только release (auto-kill снят) —
  убедиться, что путь не убивает сэндбокс

## 5. HTTP-gateway

- [x] 5.1 `server/app.py`: `GET /api/sandboxes/instances` — список Экземпляров (wire)
- [x] 5.2 `server/app.py`: `POST /api/sandboxes/instances/{id}/kill` — ручное убийство
- [x] 5.3 `server/wire.py`: сериализация Экземпляра (external id, status, runId, времена)

## 6. Тесты

- [x] 6.1 `tests/unit`: выбор сэндбокса в воркере (resume+alive → connect; dead → create),
  идемпотентность kill (на фейках портов)
- [x] 6.2 `tests/integration/test_run_store_pg.py` (или новый): PG-CRUD Экземпляров
- [x] 6.3 `task check` зелёный

## 7. Документация

- [x] 7.1 CLAUDE.md: секция про Экземпляры Сэндбокса (таблица, lifecycle, no-TTL, kill)
- [x] 7.2 CONTEXT.md: термины «Экземпляр Сэндбокса», «Пресет Сэндбокса»
