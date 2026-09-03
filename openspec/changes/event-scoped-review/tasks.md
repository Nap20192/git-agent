# event-scoped-review — Tasks

- [x] 1.1 `events.py`: optional `beforeSha/baseSha/headSha/prNumber/prTitle/prBody/changedFiles`, `has_code_target`, нулевой sha = None
- [x] 1.2 `core/repo.py::ensure_commits` — fetch по sha, merge-base для PR, `--unshallow` при нужде
- [x] 1.3 `executor._event_prompt` по action (push / PR / manual / full_scan / прочее) + `_ensure_scope` перед ходом
- [x] 1.4 `service._handle_event`: `skipped_no_commit` с `processed_at`
- [x] 2.1 Тесты: парсер, промпты по маркерам, skipped_no_commit, ensure_commits
- [x] 2.2 CLAUDE.md (Раннер), спека runner
