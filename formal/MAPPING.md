# RuntimeCore.lean → core/runtime: карта портирования

Модель описывает deer-flow runtime; наш рантайм — его адаптация (thread == run),
поэтому часть теорем переносится напрямую, часть — с оговорками, часть неприменима.

| Lean | Наш аналог | Где живёт |
|---|---|---|
| `RunStatus` | `RunStatus` (без `timeout`: таймаут = `failed` + `stop_reason='timeout'`; `success→succeeded`, `error→failed`) | `core/runtime/schemas.py` |
| `Step` (легальные переходы) | `LEGAL_TRANSITIONS` + `assert_transition()` — tripwire в каждой мутации MemoryRunStore; в Postgres те же предусловия зашиты в WHERE-условия CAS | `schemas.py`, `store_memory.py`, `infra/run_store.py` |
| `terminal_absorbing` | succeeded — абсолютно поглощающий. **Расхождение**: `failed\|interrupted → pending` существует, но только через `claim` (resume). В терминах модели resume — свежий `SysStep.admit` новой попытки того же ресурса, не `Step` | тест `test_terminal_absorbing_mirror` |
| `step_target_sound` | цель любого перехода — running, терминал или pending-через-claim | тест `test_step_targets_sound_mirror` |
| `Sys.admitted` / `Invariant` | thread == run ⇒ admission вырождается в «активная строка runs с валидным lease + owner_worker_id». `Invariant`: каждый running-ран имеет owner | тест `test_admission_invariant_mirror` (рандомизированные последовательности операций) |
| `SysStep.admit` (тред свободен) | `claim`: ConflictError при активном ране с валидным lease | `test_claim_lifecycle` |
| `SysStep.start` (нельзя стартовать без admission) | `start_run` CAS: только pending и только совпавший owner | `test_start_run_cas` |
| `SysStep.finalize` (снимает admission) | terminal CAS + `owner_worker_id=NULL` в takeover; для обычного finish владение прекращается терминальностью строки | `test_terminal_status_never_overwritten` |
| `exclusive` | два активных рана одной идентичности невозможны (unique index + claim) | `test_exclusive_mirror` |
| `inv_init` | пустой store тривиально удовлетворяет инварианту | часть `test_admission_invariant_mirror` |
| `canRead` / `full_never_reads_delta` | **Неприменимо**: delta-режим чекпоинтов не портирован (только full/PostgresSaver). Гейт понадобится, если delta появится | — |
| `Rollback` / `restore_exact` | **Неприменимо**: rollback заменён resumability (частичный чекпоинт — желаемое состояние, а не порча) | — |

Верификация: доказательства проверяются **внутри pytest** —
`test_formal.py::test_runtime_core_proofs_check` шеллит `lean` и требует
exit 0 + ноль `sorry` (скипается, если lean не установлен). Отдельно:
`formal/check.sh` или `task formal`. Lean 4.33.1. Python-тесты-зеркала
теорем — `test_invariants.py`.
