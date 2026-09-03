-- Режим подключения Репозитория (тикет 015): hook — свой репо, хук ставит hub;
-- watch — чужой публичный репо по URL, без хука и без связки, запуск руками.

ALTER TABLE hub.repositories ADD COLUMN mode TEXT NOT NULL DEFAULT 'hook' CHECK (mode IN ('hook', 'watch'));
ALTER TABLE hub.repositories ALTER COLUMN identity_id DROP NOT NULL;
