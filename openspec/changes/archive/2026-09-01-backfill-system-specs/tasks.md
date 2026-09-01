# Tasks: backfill-system-specs

## 1. Верификация спек против исполняемых зеркал

- [x] 1.1 durable-runs: каждое требование покрыто formal/RuntimeCore.lean и/или tests/unit/test_runtime.py
- [x] 1.2 lead-delegation: каждое требование покрыто tests/unit/subagents/ + tests/unit/middleware/
- [x] 1.3 memory-presets: резолв и ошибки покрыты тестами core/memory
- [x] 1.4 eval-harness: каждое требование покрыто tests/unit/eval/test_harness.py
- [x] 1.5 agent-graph (MODIFIED): требование соответствует фактическому CLI (--mode, durable-рантайм)

## 2. Валидация

- [x] 2.1 `openspec validate --changes` без ошибок
