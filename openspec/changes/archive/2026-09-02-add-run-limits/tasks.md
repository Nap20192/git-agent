# Tasks: add-run-limits
- [ ] 1.1 Миграция runs.limits JSONB; store.set_limits; memory-store паритет
- [ ] 1.2 Runtime.submit(limits) персистит на created; worker читает limits (переданные|из строки)
- [ ] 1.3 profile.build(..., limits); lead строит RuntimeFeatures+SubagentCapacity из лимитов
- [ ] 1.4 Gateway submit: лимиты из features; resume: опц. новые лимиты (set_limits перед resubmit)
- [ ] 1.5 Frontend: продолжение с поднятым бюджетом; тесты; task check + bun build; archive
