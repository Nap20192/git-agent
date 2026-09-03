-- Находка v2 + структурированный отчёт. Пишет раннер (report_finding + git blame),
-- читает hub (GET findings / export). Все новые колонки NULL-able: старые строки
-- и Находки без blame. Значения enum-полей (confidence/category/introduced_by)
-- валидирует раннер — CHECK'ов нет намеренно, чтобы неожиданное значение
-- не потеряло Находку. "references" — зарезервированное слово, в SQL только в кавычках.

ALTER TABLE hub.findings
    ADD COLUMN title                TEXT,
    ADD COLUMN description          TEXT,
    ADD COLUMN impact               TEXT,
    ADD COLUMN confidence           TEXT,        -- high | medium | low
    ADD COLUMN category             TEXT,        -- injection | auth | crypto | secrets | deps | config | xss | ssrf | path | logic | other
    ADD COLUMN "references"         JSONB,       -- []string
    ADD COLUMN blame_author         TEXT,
    ADD COLUMN blame_email          TEXT,
    ADD COLUMN blame_commit         TEXT,
    ADD COLUMN blame_date           TIMESTAMPTZ,
    ADD COLUMN blame_commit_message TEXT,
    ADD COLUMN introduced_by        TEXT,        -- this_event | earlier
    ADD COLUMN event_id             BIGINT REFERENCES hub.events; -- какое Событие породило Находку

-- (instance_id, severity) покрывает и старый (instance_id) как префикс
DROP INDEX IF EXISTS hub.findings_instance;
CREATE INDEX findings_instance_severity ON hub.findings (instance_id, severity);

-- structured: {summary, scope{eventType, range, filesTouched, linesChanged}, method[],
-- findingsBySeverity{critical,high,medium,low,info}, topRisks[], recommendations[], limitations[]};
-- summary — markdown-рендер той же структуры (делает раннер).
ALTER TABLE hub.reports ADD COLUMN structured JSONB;
