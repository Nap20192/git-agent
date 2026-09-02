## Context

Воркер (`core/runtime/worker.py`) создаёт сэндбокс на Ран через
`create_sandbox_by_name` и в `finally` зовёт `sandbox.close()`. В OpenSandbox-
адаптере `close()` = `self._sandbox.kill()` — удалённый сэндбокс уничтожается.
OpenSandbox по умолчанию даёт сэндбоксу конечный TTL (в SDK — `timedelta(minutes=30)`,
на сервере наблюдалось 600s), поэтому прерванный Ран переживает своё окружение и
даёт `ConnectError` на последующих командах. Таблица `sandboxes` хранит **пресеты**
(git/python/local: kind+image), не живые экземпляры.

SDK умеет всё нужное: `Sandbox.create(..., timeout=None)` (manual-cleanup),
`sandbox.id`, `Sandbox.connect(id, skip_health_check=True)`, `kill()` (убить
remote), `close()` (отпустить только локальный HTTP), `destroy()` (kill+close).

## Goals / Non-Goals

**Goals:**
- Сэндбоксы без TTL; воркер не убивает их на завершении.
- Учёт Экземпляров (external id, run, status alive/dead) в отдельной таблице.
- Resume переподключается к живому Экземпляру Рана по id.
- Ручное убийство Экземпляра + список — через gateway.

**Non-Goals:**
- Фоновый поллер/reconciler живости (статус ведём по нашим действиям + fallback
  при неудачном reconnect). Оркестрация пулов OpenSandbox не используется.
- Переподключение для `local`-сэндбокса (эфемерный temp-dir, не учитывается).
- Frontend-экран управления Экземплярами (следующий change, если понадобится).

## Decisions

**Экземпляр ≠ Пресет — отдельная таблица.** `sandboxes` держит пресеты с UNIQUE
`name` и seed-строками; Экземпляр — много на пресет, с эфемерным external id и
жизненным циклом. Смешивать нельзя (сломает UNIQUE и семантику). Новая таблица
`sandbox_instances(external_id UNIQUE, kind, image, run_id→runs, status
alive|dead, created_at, killed_at)`.

**Связь Ран↔Экземпляр — через `run_id` в Экземпляре, без ALTER runs.** Resume
находит живой Экземпляр: `WHERE run_id=%s AND status='alive' ORDER BY id DESC
LIMIT 1`. Достаточно, второй столбец на `runs` не нужен.

**Семантика `close()` меняется на «release».** `OpenSandboxAdapter.close()` теперь
`self._sandbox.close()` (только HTTP), а не `kill()`. Это и есть снятие auto-kill:
воркер в `finally` отпускает локальные ресурсы, но не трогает контейнер.
`LocalSandbox.close()` остаётся `rmtree` (эфемерный, не переподключается).

**Ручной kill идёт по external id, без живого объекта.**
`infra/sandbox_instances.py::kill_sandbox(instance_id)`:
`Sandbox.connect(external_id, skip_health_check=True)` → `.destroy()` →
`UPDATE status='dead', killed_at=now()`. Идемпотентно: если Экземпляр уже `dead`,
БД-апдейт no-op, `destroy` не зовём.

**Выбор сэндбокса — в воркере, не в `create_sandbox_by_name`.** Порт-функция
остаётся «создать по имени». Воркер решает create-vs-connect: получает spec по
имени, и либо `connect` (resume+alive), либо `create(timeout=None)`+запись
Экземпляра+`prepare`. Reconnect обходит `prepare` (репо уже склонировано).

**Порт `Sandbox` получает `id`.** `str | None` (external id; `None` для local),
чтобы воркер знал, что писать в Экземпляр.

## Risks / Trade-offs

- **Утечка живых сэндбоксов.** «Только вручную» = брошенные Экземпляры копятся и
  жрут ресурсы. Смягчение: список показывает всех живых; kill доступен; воркер
  метит `dead` при неудачном reconnect. Явно принятый пользователем компромисс.
- **Дрейф статуса.** Сэндбокс может умереть извне (рестарт хоста), а запись
  останется `alive`. Ловим лениво: reconnect упадёт → метим `dead` + fallback.
  Фоновый reconciler — вне скоупа.
- **Смена семантики `close()`** затрагивает всех вызывающих порт. Вызовы: воркер и
  CLI (`main.py`). Оба — «отпустить в конце», release корректен; kill теперь
  только через явный путь.
