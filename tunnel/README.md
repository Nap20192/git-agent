# tunnel — стабильный адрес для вебхуков

Релей на Railway вместо trycloudflare: вечный публичный URL принимает `POST /hooks/*` и складывает запросы в очередь в памяти (1000, старое вытесняется); локальный пуллер рядом с hub забирает их длинным поллингом (`GET /pull?wait=25s`, auth — заголовок `X-Relay-Token`) и переигрывает в `http://localhost:8081` с исходными путём, заголовками и телом — HMAC-подпись провайдера доезжает нетронутой, hub верифицирует как обычно. Доставка at-most-once: потерянное можно redeliver из UI GitHub/GitLab.

Деплой: `railway login`, затем из `tunnel/` — `railway init` (один раз) и `task relay:deploy` (это `railway up`; сборка по Dockerfile, healthcheck `/healthz`). В сервисе Railway задай переменную `RELAY_TOKEN` (сгенерируй: `openssl rand -hex 32`) и сгенерируй публичный домен (Settings → Networking → Generate Domain); `PORT` Railway выставляет сам.

Локально: в `.env` пропиши `RELAY_URL=https://<railway-домен>`, тот же `RELAY_TOKEN`, и `WEBHOOK_BASE_URL=https://<railway-домен>` (hub подставит его в URL хуков при создании). Пуллер: `task relay:pull` (env `HUB_URL` — куда переигрывать, дефолт `http://localhost:8081`). `scripts/retunnel.sh` остаётся fallback-путём через cloudflared.
