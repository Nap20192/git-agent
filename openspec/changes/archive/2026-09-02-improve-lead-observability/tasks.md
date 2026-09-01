# Tasks: improve-lead-observability

- [x] 1.1 store.delete_run (checkpoints+run_events+row в транзакции; guard на активный)
- [x] 1.2 DELETE /api/runs/{id}; 409 на активном
- [x] 1.3 event_to_wire: разбор lead updates → agent_step (reasoning/tool_calls/results); skip middleware
- [x] 1.4 graphview: активность Лида (tool_calls, findings) на узле
- [x] 1.5 frontend: api.deleteRun + кнопка; describe() agent_step
- [x] 1.6 тесты; task check + bun build; archive
