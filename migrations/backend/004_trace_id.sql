-- Сквозной trace_id (32 hex, pkg/trace): События и activity-кадры ищутся по
-- одному id вместе с логами hub/раннера и трейсами Langfuse/LangSmith.
-- '' — строки до миграции.

ALTER TABLE hub.events   ADD COLUMN trace_id TEXT NOT NULL DEFAULT '';
ALTER TABLE hub.activity ADD COLUMN trace_id TEXT NOT NULL DEFAULT '';

CREATE INDEX events_trace   ON hub.events   (trace_id) WHERE trace_id <> '';
CREATE INDEX activity_trace ON hub.activity (trace_id) WHERE trace_id <> '';
