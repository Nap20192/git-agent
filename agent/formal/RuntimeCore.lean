/-!
# RuntimeCore — верифицированное ядро агентского рантайма (модель DeerFlow runtime)

Три подсистемы, каждая с доказанными инвариантами:

1. Статусная машина рана          → `Step`, `terminal_absorbing`
2. Admission: эксклюзив на тред   → `Sys`, `Invariant`, `inv_preserved`, `exclusive`
3. Гейт режимов чекпоинта         → `canRead`, `full_never_reads_delta`

Ноль зависимостей (без mathlib): проверяется `lean RuntimeCore.lean`.
Каждый def здесь — прямой аналог кода в deerflow/runtime; портируй defs,
инварианты переноси как тесты/asserts.
-/

/-! ## 1. Жизненный цикл рана (runs/schemas.py::RunStatus) -/

inductive RunStatus
  | pending | running | success | error | timeout | interrupted
  deriving DecidableEq, Repr

def RunStatus.isTerminal : RunStatus → Bool
  | .success | .error | .timeout | .interrupted => true
  | .pending | .running => false

/-- Легальные переходы (статусная машина runs/manager.py).
`abortPending` — startup barrier: отмена догнала ран до старта,
агент не строился вообще. -/
inductive Step : RunStatus → RunStatus → Prop
  | start        : Step .pending .running
  | finish       : Step .running .success
  | fail         : Step .running .error
  | timedOut     : Step .running .timeout
  | interrupt    : Step .running .interrupted
  | abortPending : Step .pending .interrupted

/-- Терминальный статус — поглощающий: из него нет переходов.
(В manager.py это «Skipped status update after terminal».) -/
theorem terminal_absorbing {s t : RunStatus} (h : Step s t) :
    s.isTerminal = false := by
  cases h <;> rfl

/-- Всякий переход ведёт либо в running, либо в терминал —
промежуточных «подвисших» статусов нет. -/
theorem step_target_sound {s t : RunStatus} (h : Step s t) :
    t = .running ∨ t.isTerminal = true := by
  cases h <;> simp [RunStatus.isTerminal]

/-! ## 2. Admission: не более одной активной операции на тред

Модель durable-резервации из runs/manager.py + ThreadOperationKind.
`Sys.admitted` — таблица admission в базе; инвариант `Invariant` — каждый
running-ран держит admission своего треда. Из него следует
эксклюзивность (`exclusive`). -/

abbrev RunId := Nat
abbrev ThreadId := Nat

structure Sys where
  /-- реестр ранов: none = не зарегистрирован -/
  status : RunId → Option RunStatus
  /-- статическая привязка ран → тред -/
  thread : RunId → ThreadId
  /-- durable admission: какой ран владеет тредом -/
  admitted : ThreadId → Option RunId

/-- ИНВАРИАНТ: каждый running-ран держит admission на свой тред. -/
def Invariant (s : Sys) : Prop :=
  ∀ id, s.status id = some .running → s.admitted (s.thread id) = some id

/-- Переходы системы. Предусловия конструкторов — это ровно те проверки,
которые обязана делать реализация (иначе инвариант недоказуем):
  * admit: тред свободен, ран новый;
  * start: ран pending И admission уже наш (нельзя стартовать без него);
  * finalize: только running и только в терминал; admission снимается. -/
inductive SysStep : Sys → Sys → Prop
  | admit (s : Sys) (id : RunId)
      (hfree : s.admitted (s.thread id) = none)
      (hnew  : s.status id = none) :
      SysStep s
        { s with
          status   := fun j => if j = id then some .pending else s.status j,
          admitted := fun t => if t = s.thread id then some id else s.admitted t }
  | start (s : Sys) (id : RunId)
      (hp : s.status id = some .pending)
      (ha : s.admitted (s.thread id) = some id) :
      SysStep s
        { s with
          status := fun j => if j = id then some .running else s.status j }
  | finalize (s : Sys) (id : RunId) (term : RunStatus)
      (hr : s.status id = some .running)
      (hterm : term.isTerminal = true) :
      SysStep s
        { s with
          status   := fun j => if j = id then some term else s.status j,
          admitted := fun t => if t = s.thread id then none else s.admitted t }

/-- ГЛАВНАЯ ТЕОРЕМА СОХРАНЕНИЯ: любой шаг системы сохраняет инвариант.
Порт: пока реализация делает только эти три операции с этими
предусловиями, running-ран без admission невозможен. -/
theorem inv_preserved {s s' : Sys} (h : Invariant s) (hs : SysStep s s') : Invariant s' := by
  cases hs with
  | admit id hfree hnew =>
      intro j hj
      simp only at hj ⊢
      by_cases hji : j = id
      · subst hji; simp at hj
      · rw [if_neg hji] at hj
        have hadm := h j hj
        by_cases ht : s.thread j = s.thread id
        · rw [ht, hfree] at hadm; exact absurd hadm (by simp)
        · rw [if_neg ht]; exact hadm
  | start id hp ha =>
      intro j hj
      simp only at hj ⊢
      by_cases hji : j = id
      · subst hji; exact ha
      · rw [if_neg hji] at hj; exact h j hj
  | finalize id term hr hterm =>
      intro j hj
      simp only at hj ⊢
      by_cases hji : j = id
      · subst hji
        simp at hj
        rw [hj] at hterm
        simp [RunStatus.isTerminal] at hterm
      · rw [if_neg hji] at hj
        have hadm := h j hj
        by_cases ht : s.thread j = s.thread id
        · -- другой running-ран на том же треде? тогда admission
          -- одновременно = some j и = some id — противоречие
          have hid := h id hr
          rw [ht] at hadm
          rw [hadm] at hid
          injection hid with h'
          exact absurd h' hji
        · rw [if_neg ht]; exact hadm

/-- СЛЕДСТВИЕ (эксклюзивность): два running-рана на одном треде —
это один и тот же ран. Ровно то, что гарантирует durable admission. -/
theorem exclusive {s : Sys} (h : Invariant s) (id1 id2 : RunId)
    (h1 : s.status id1 = some .running)
    (h2 : s.status id2 = some .running)
    (ht : s.thread id1 = s.thread id2) : id1 = id2 := by
  have a1 := h id1 h1
  have a2 := h id2 h2
  rw [ht] at a1
  exact Option.some.inj (a1.symm.trans a2)

/-- Инвариант достижим: пустая система ему удовлетворяет
(база индукции для «Invariant верен всегда»). -/
theorem inv_init : Invariant ⟨fun _ => none, fun _ => 0, fun _ => none⟩ := by
  intro id hid; simp at hid

/-! ## 3. Гейт совместимости режимов чекпоинта (checkpoint_mode.py)

Асимметричный fail-closed: full-процесс НЕ читает delta-тред
(сырое чтение вернуло бы пустые messages); delta-процесс читает
всё — это путь миграции full → delta. -/

inductive Mode | full | delta
  deriving DecidableEq, Repr

/-- процесс `p` может открыть чекпоинт, записанный в режиме `c` -/
def canRead : (p : Mode) → (c : Mode) → Bool
  | .delta, _     => true
  | .full,  .full => true
  | .full,  .delta => false

/-- ФЕЙЛ-КЛОУЗ: full-процесс никогда не открывает delta-чекпоинт
(в реализации — CheckpointModeMismatchError / HTTP 409). -/
theorem full_never_reads_delta : canRead .full .delta = false := rfl

/-- ПУТЬ МИГРАЦИИ: delta-процесс читает чекпоинты любого режима. -/
theorem delta_reads_everything (c : Mode) : canRead .delta c = true := by
  cases c <;> rfl

/-- Чтение «своего» режима всегда разрешено (совместимость с собой). -/
theorem same_mode_ok (m : Mode) : canRead m m = true := by
  cases m <;> rfl

/-! ## 4. Rollback: fail-closed на снимке (runs/worker.py::RollbackPoint)

Восстановление возможно только из целиком снятого снимка;
неудавшийся capture отключает rollback — частичного восстановления
не существует по построению (это тип, а не проверка в рантайме). -/

inductive Rollback (α : Type)
  | captured (snapshot : α)
  | disabled

def Rollback.restore {α : Type} : Rollback α → Option α
  | .captured s => some s
  | .disabled   => none

/-- Если restore что-то вернул — это в точности снятый снимок:
частичное/сфабрикованное состояние невыразимо. -/
theorem restore_exact {α : Type} (r : Rollback α) (x : α)
    (h : r.restore = some x) : r = .captured x := by
  cases r with
  | captured s => simp [Rollback.restore] at h; rw [h]
  | disabled   => simp [Rollback.restore] at h
