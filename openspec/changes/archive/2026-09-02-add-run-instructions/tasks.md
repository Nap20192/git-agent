# Tasks: add-run-instructions

## 1. Core

- [x] 1.1 `GraphProfile.make_input` принимает `instructions`; lead-профиль подставляет её вместо `_LEAD_TASK`, pipeline игнорирует
- [x] 1.2 Проброс: `Runtime.submit(instructions=…)` → worker → make_input (только не-resume)

## 2. Входы

- [x] 2.1 CLI: флаг `--task`
- [x] 2.2 Gateway: поле `instructions` в POST /runs; openapi.yaml обновлён
- [x] 2.3 UI: textarea задачи в форме нового Рана (contract.ts + RunsScreen)

## 3. Проверка

- [x] 3.1 Тесты: lead make_input с/без instructions; runtime доносит instructions до графа; gateway передаёт поле
- [x] 3.2 `task check` + `bun run build` зелёные; archive change
