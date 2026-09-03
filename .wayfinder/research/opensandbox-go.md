# Research: OpenSandbox из Go

Дата: 2026-09-03. Источники: deploy/docker-compose.yml, установленный Python SDK
(`.venv/lib/python3.13/site-packages/opensandbox/`, сгенерирован из OpenAPI), GitHub проекта.

## Go SDK: есть

Официальный Go SDK живёт в монорепе проекта:
<https://github.com/alibaba/OpenSandbox/blob/main/sdks/sandbox/go/README.md>
(зеркало/оргалиас — opensandbox-group/OpenSandbox; в headers Python SDK copyright Alibaba).

```
go get github.com/alibaba/OpenSandbox/sdks/sandbox/go
```

Покрывает lifecycle (create/get/pause/resume/delete), execd (run command, streaming),
network policy. Клиенты конструируются от base URL + api key, без env-магии:

```go
lc := opensandbox.NewLifecycleClient("http://localhost:8090/v1", "dev-local-key")
sbx, _ := lc.CreateSandbox(ctx, opensandbox.CreateSandboxRequest{...})
// sbx.ID — это и есть external_id
```

## HTTP API (lifecycle-сервер, наш инстанс: http://localhost:8090/v1)

Auth на все запросы: заголовок `OPEN-SANDBOX-API-KEY: dev-local-key`.
Base URL = `{domain}/v1` (Python SDK: `config/connection.py::get_base_url`).

| Метод | Путь | Тело / параметры | Возвращает |
|---|---|---|---|
| POST | `/v1/sandboxes` | `{image: {uri}, entrypoint: [...], resourceLimits, env, metadata, timeout, ...}`; `timeout: null` = no-TTL (наш режим) | **202** `{id, status, createdAt, entrypoint, expiresAt?}` — `id` = external_id |
| GET | `/v1/sandboxes/{id}` | — | инфо о сэндбоксе (status и пр.) — это «connect» на стороне сервера |
| DELETE | `/v1/sandboxes/{id}` | — | destroy |
| GET | `/v1/sandboxes/{id}/endpoints/{port}` | port=44772 (execd), 18080 (egress) | `{endpoint: "host:port", headers?}` — адрес порта внутри сэндбокса |
| POST | `/v1/sandboxes/{id}/pause` \| `/resume` \| `/renew_expiration` | — | pause/resume/продление TTL |
| GET | `/v1/sandboxes` | — | список |

«Connect» в SDK — не отдельный эндпоинт: это GET `/v1/sandboxes/{id}` (health/status)
плюс резолв execd-endpoint через `/endpoints/44772`.

## Execd API (внутри сэндбокса, base = резолвнутый endpoint)

| Метод | Путь | Что |
|---|---|---|
| GET | `/ping` | health |
| POST | `/command` | run command (streaming stdout/stderr events), `{command, timeout}` |
| POST | `/session` | интерактивная сессия |
| + filesystem | `/files...` | upload/download/list и пр. |

Порты по умолчанию: execd 44772, egress 18080 (`opensandbox/constants.py`).

## Вывод

Тонкий Go HTTP-клиент — хватает с запасом для create/connect(status)/destroy:
это 3 JSON-вызова с одним заголовком. Но писать его не нужно — есть официальный
Go SDK в той же монорепе, который к тому же закрывает стриминг команд execd
(единственное нетривиальное место). Рекомендация: взять Go SDK; если хочется
нулевых зависимостей — тонкий клиент lifecycle-части тривиален, execd-стриминг
руками писать дороже, чем импортировать SDK.
