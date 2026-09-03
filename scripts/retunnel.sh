#!/usr/bin/env bash
# Перезапуск cloudflared-туннеля к hub (:8081) + перепрописывание GitHub-хуков
# всех подключённых репозиториев на новый URL (+ ping для проверки доставки).
# trycloudflare выдаёт случайный URL на каждый запуск — поэтому хуки надо
# обновлять каждый раз. Hub перезапускать не нужно: WEBHOOK_BASE_URL читается
# только при создании новых хуков.
set -euo pipefail
cd "$(dirname "$0")/.."

CLOUDFLARED="${CLOUDFLARED:-$HOME/.local/bin/cloudflared}"
LOG="${TUNNEL_LOG:-/tmp/git-agent-tunnel.log}"

pkill -f "cloudflared tunnel --url http://localhost:8081" 2>/dev/null || true
sleep 1
: > "$LOG"
nohup "$CLOUDFLARED" tunnel --url http://localhost:8081 >>"$LOG" 2>&1 &
echo "cloudflared запущен (лог: $LOG), жду URL…"

URL=""
for _ in $(seq 30); do
  URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG" | head -1 || true)
  [ -n "$URL" ] && break
  sleep 2
done
[ -n "$URL" ] || { echo "ОШИБКА: туннель не выдал URL, см. $LOG"; exit 1; }

sed -i "s|^WEBHOOK_BASE_URL=.*|WEBHOOK_BASE_URL=$URL|" .env
echo "туннель: $URL (записан в .env), жду готовности edge…"

# edge Cloudflare регистрируется с лагом; ping до готовности GitHub не ретраит.
# Резолвим через 1.1.1.1 — системный resolved может флапать на новых доменах.
HOST="${URL#https://}"
ready=""
for _ in $(seq 20); do
  IP=$(nslookup -type=A "$HOST" 1.1.1.1 2>/dev/null | awk '/^Address: /{print $2}' | grep -E '^[0-9.]+' | head -1 || true)
  if [ -n "$IP" ] && [ "$(curl -s -m 8 -o /dev/null -w '%{http_code}' --resolve "$HOST:443:$IP" "$URL/healthz" 2>/dev/null)" = "200" ]; then
    ready=1; break
  fi
  sleep 3
done
[ -n "$ready" ] || echo "ПРЕДУПРЕЖДЕНИЕ: edge не подтвердил готовность, хуки всё равно перепропишу"

( cd agent && uv run python ../scripts/rehook.py "$URL" )
