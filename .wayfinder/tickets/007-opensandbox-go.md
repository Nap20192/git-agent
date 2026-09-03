# Research: OpenSandbox из Go

Type: wayfinder:research
Status: closed
Assignee: agent
Blocked by: —

## Question

Есть ли у OpenSandbox Go SDK? Если нет — каков его HTTP API для create / connect / destroy sandbox (тот сервис, что поднят в deploy/docker-compose.yml на :8090, dev-ключ dev-local-key): эндпоинты, аутентификация, формат ответа с external_id. Достаточно ли для Go-сервиса тонкого HTTP-клиента.

## Answer

Официальный Go SDK есть: `go get github.com/alibaba/OpenSandbox/sdks/sandbox/go`
(lifecycle + execd + network policy). HTTP API тривиален: base `http://localhost:8090/v1`,
заголовок `OPEN-SANDBOX-API-KEY`; `POST /sandboxes` → 202 `{id,...}` (`id` = external_id),
`GET/DELETE /sandboxes/{id}`, execd-endpoint через `GET /sandboxes/{id}/endpoints/44772`.
Тонкого клиента хватило бы, но брать SDK — он закрывает стриминг команд execd.
Детали: [research/opensandbox-go.md](../research/opensandbox-go.md).
