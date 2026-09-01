# Proposal: add-run-instructions

## Why

Задача агентного Рана зашита в коде (`_LEAD_TASK`): чтобы попросить лида «опиши каждую функцию», приходится править исходники. Пользователь должен уметь задавать вход Рана (instructions) при запуске — из CLI и из UI-формы.

## What Changes

- Ран принимает опциональные instructions — пользовательский текст задачи; в агентном режиме он замещает дефолтную задачу лида (плейсхолдер `{repo_url}` подставляется), в pipeline-режиме игнорируется (вход фиксирован).
- Instructions действуют при создании Рана; Возобновление продолжает с Чекпоинта и не переигрывает вход (существующая семантика resume).
- CLI: флаг `--task`; HTTP: поле `instructions` в SubmitRunRequest (openapi.yaml — авторитетный контракт); UI: поле в форме нового Рана.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `agent-graph`: требование «Запуск из CLI» дополняется пользовательской задачей Рана.

## Impact

- `core/runtime/profile.py` (make_input), `core/runtime/{runtime,worker}.py` (проброс), `core/lead/graph.py`, `main.py`, `server/app.py`, `frontend/docs/openapi.yaml`, `frontend/src` (contract + форма).
- Идентичность Рана НЕ включает instructions (как и режим): повторный submit той же (repo, commit, model) с другой задачей присоединится к существующему Рану — ограничение документируется.
