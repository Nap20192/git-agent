-- Диапазон изменений События (diff-контекст): агент аудитит конкретный дифф,
-- а не весь репозиторий. before_sha — push (пусто при force-push / новой
-- ветке); base_sha/head_sha + pr_* — PR/MR; changed_files — из коммитов push
-- (PR — NULL, раннер берёт из diff). Всё NULL-able: старые строки и manual/full.

ALTER TABLE hub.events
    ADD COLUMN before_sha    TEXT,
    ADD COLUMN base_sha      TEXT,
    ADD COLUMN head_sha      TEXT,
    ADD COLUMN pr_number     INT,
    ADD COLUMN pr_title      TEXT,
    ADD COLUMN pr_body       TEXT,
    ADD COLUMN changed_files JSONB;
