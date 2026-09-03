# runner-consumer — Design

## Context

См. proposal.md (Why) и `.wayfinder/tickets/001,004,005`. Схема `hub.*` применена (`migrations/backend/001_init.sql`). Backend — скелет: форматы сообщения События, форварда и регистрации фиксируем мы; хаб-клиент за портом с деградацией. У агента уже есть всё исполняющее ядро: `build_lead_profile()` (граф лида с чекпоинтером), `make_model`, `OpenSandboxAdapter`, `prepare_repo`, `AsyncPostgresSaver`. Раннер — второй вход в это ядро, параллельный gateway; Runtime/durable-runs не трогаем (Ран и Экземпляр — разные ресурсы: у Экземпляра нет admission/lease, гарантии дают дедуп-журнал + чекпоинты, ткт 001).

## Goals / Non-Goals

**Goals**: минимальный работающий Раннер v1 по спеке `runner`; гексагональность (домен `core/runner/` зависит только от портов); герметичные unit-тесты.

**Non-Goals**: изменение существующего gateway/Runtime; publisher в Rabbit (только консьюмер); киллинг песочниц; профили агентов; горизонтальная координация раннеров сверх CAS+форварда; backend-сторона (ре-публикация, heartbeat-надзор).

## Decisions

- **aio-pika, auto-ack** — единственный зрелый async-клиент; auto-ack прямо по тикету 001 (гарантии — БД+чекпоинты, не ack).
- **Домен в `core/runner/`, порты там же** (`ports.py`: `InstanceStore`, `HubClient`, `EventForwarder` — по образцу `core/ports.py`). Адаптеры: `infra/db/hub_store.py` (psycopg над `hub.*`, отдельного пула не заводим — тот же `DATABASE_URL`), `infra/hub_client.py` (httpx: регистрация/heartbeat/форвард), `infra/rabbit.py` (консьюмер → callback сервиса).
- **Слот = запись в dict Экземпляров + asyncio.Semaphore(N)**; Экземпляр в памяти — лёгкий объект (last_activity, lock, sandbox handle). Идемпотентный подъём. Idle-репер — один фоновый цикл. `# ponytail:` на семафоре — очередь без приоритета, хватит для v1.
- **Исполнение = один ход лид-графа на тред Экземпляра** (`thread_id` из События), по образцу `Runtime.chat`: `profile.build(sandbox, model, checkpointer).astream({messages:[HumanMessage(текст События)]})`. Никакого нового executor-фреймворка.
- **Тулзы результатов**: `build_hub_security_tools(instance_id, event_id)` — обёртки, которые реально пишут в `hub.findings`/`hub.reports` (тикет 001: «результат агент пишет в БД сам, через тулзу»). Существующий `report_finding` (валидация) переиспользуем как схему; вставка — через порт `InstanceStore`.
- **Расшифровка `*_enc`**: AES-GCM, формат `nonce(12) || ciphertext`, ключ — env `HUB_ENC_KEY` (base64, 32 байта). Backend пишется после — формат фиксируется здесь и в `.env.example`. `cryptography` уже в venv (транзитивно) — поднимаем в прямые зависимости.
- **Sandbox per Экземпляр** из `hub.sandbox_connections` (domain/api_key/image): `create_sandbox()` получает опциональные `domain/api_key`; внешний id пишем в `hub.sandbox_instances` + линкуем `agent_instances.sandbox_instance_id`; при подъёме сперва пробуем reconnect к живому. Repo URL строим из `hub.repositories` (`https://{host}/{owner}/{name}`).
- **Чекпоинтер** — тот же `AsyncPostgresSaver` (одна БД); треды Экземпляров не пересекаются с тредами Ранов, т.к. `thread_id` приходит от hub'а (`threadId` События).
- **Точка входа** — `runner.py` (`app = create_runner_app()`, uvicorn): FastAPI со `lifespan`, поднимающим консьюмер, heartbeat и idle-цикл. Отдельный от `main.py` — раннер и gateway деплоятся независимо.
- **Форвард не ретраится и не буферизуется**: запись дедуп-журнала уже есть (вставили до форварда? нет — вставляет держатель). Решение: журнал пишет ТОТ, кто исполняет; форвардер при недоступности держателя — warn, Событие потеряно до ре-публикации backend'ом (его надзор за heartbeat — вне скоупа).

## Risks / Trade-offs

- [Backend ещё пишется — контракты могут разъехаться] → все интеграции за портами; форматы задокументированы в спеке; смена — правка адаптера.
- [Auto-ack: смерть раннера посреди исполнения теряет Событие] → так решено тикетом 001: запись без `processed_at` + heartbeat-надзор backend'а ре-публикует; чекпоинт-тред не теряет накопленного.
- [Гонка клейма между раннерами] → CAS одним UPDATE'ом с `WHERE status='down'`; проигравший идёт по ветке форварда.
- [Два процесса (gateway + раннер) делят sync-пул psycopg] → пулы процесс-локальные, конфликтов нет.

## Migration Plan

Аддитивно: новые файлы + ключи env. Запуск — `uv run uvicorn runner:app --port 8081`. Откат — не запускать раннер.

## Open Questions

- Точный путь/схема регистрации у backend (`/api/runners`) — уточнится, когда появится `backend/docs/openapi.yaml`; правка — только в `infra/hub_client.py`.
