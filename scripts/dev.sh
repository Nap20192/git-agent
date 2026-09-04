#!/usr/bin/env bash
# Dev-стек: hub (:8081), раннер (:8082), фронт (:5173), puller.
#   up [name…]     — поднять недостающее; down [name…] — погасить; status — кто жив
# Внутри Herdr (HERDR_ENV=1) каждый сервис живёт в своей панели workspace «app»
# (панели находятся по label, недостающие создаются); вне Herdr — в фоне с
# pid-файлами в .dev/ и JSON-логами в logs/dev/<name>.log.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUN="$ROOT/.dev"; LOG="$ROOT/logs/dev"; mkdir -p "$RUN" "$LOG"
ALL="hub runner front puller"
WS_LABEL=app

cmd_of() { case $1 in
  hub)    echo "cd '$ROOT' && set -a && . ./.env && set +a && task backend:run" ;;
  runner) echo "cd '$ROOT' && task runner" ;;
  front)  echo "cd '$ROOT' && task front" ;;
  puller) echo "cd '$ROOT' && task relay:pull" ;;
esac; }
port_of() { case $1 in hub) echo 8081;; runner) echo 8082;; front) echo 5173;; *) echo "";; esac; }
url_of() { case $1 in hub) echo http://localhost:8081/healthz;; runner) echo http://localhost:8082/health;; front) echo http://localhost:5173/;; esac; }

is_up() { # по порту; puller — по процессу
  local port; port=$(port_of "$1")
  if [ -n "$port" ]; then lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
  else pgrep -f '[c]md/puller' >/dev/null; fi
}
wait_up() { local i; for i in $(seq 1 "${2:-90}"); do is_up "$1" && { [ -z "$(url_of "$1")" ] || curl -sf -o /dev/null "$(url_of "$1")"; } && return 0; sleep 1; done
  echo "$1: not ready after ${2:-90}s" >&2; return 1; }
wait_down() { local i; for i in $(seq 1 "${2:-20}"); do is_up "$1" || return 0; sleep 1; done; return 1; }
kill_hard() { local port; port=$(port_of "$1")
  if [ -n "$port" ]; then kill $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null) 2>/dev/null || true
  else kill $(pgrep -f '[c]md/puller') 2>/dev/null || true; fi; }

# ── herdr ────────────────────────────────────────────────────────────────────
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print(eval('d$1'))" 2>/dev/null; }
ws_id() { herdr workspace list | python3 -c "
import sys,json
for w in json.load(sys.stdin)['result']['workspaces']:
    if w.get('label')=='$WS_LABEL': print(w['workspace_id']); break"; }
pane_by_label() { herdr pane list --workspace "$1" | python3 -c "
import sys,json
for p in json.load(sys.stdin)['result']['panes']:
    if p.get('label')=='$2': print(p['pane_id']); break"; }
pane_busy() { herdr pane process-info --pane "$1" | python3 -c "
import sys,json; print('busy' if json.load(sys.stdin)['result']['process_info'].get('foreground_processes') else '')"; }

ensure_ws() {
  local ws; ws=$(ws_id)
  if [ -z "$ws" ]; then
    local out; out=$(herdr workspace create --label "$WS_LABEL" --cwd "$ROOT" --no-focus)
    ws=$(echo "$out" | jq_ "['result']['workspace']['workspace_id']")
    local root; root=$(echo "$out" | jq_ "['result']['root_pane']['pane_id']")
    herdr pane rename "$root" hub >/dev/null
  fi
  echo "$ws"
}
# раскладка: hub | front ; под hub — runner, под front — puller
ensure_pane() { # ensure_pane <ws> <name> → pane id
  local ws=$1 name=$2 id; id=$(pane_by_label "$ws" "$name")
  if [ -n "$id" ]; then echo "$id"; return; fi
  local anchor dir
  case $name in
    hub)    anchor=$(herdr pane list --workspace "$ws" | jq_ "['result']['panes'][0]['pane_id']"); herdr pane rename "$anchor" hub >/dev/null; echo "$anchor"; return ;;
    front)  anchor=$(ensure_pane "$ws" hub);   dir=right ;;
    runner) anchor=$(ensure_pane "$ws" hub);   dir=down ;;
    puller) anchor=$(ensure_pane "$ws" front); dir=down ;;
  esac
  id=$(herdr pane split "$anchor" --direction "$dir" --cwd "$ROOT" --no-focus | jq_ "['result']['pane']['pane_id']")
  herdr pane rename "$id" "$name" >/dev/null
  echo "$id"
}
herdr_up() {
  local ws; ws=$(ensure_ws)
  for name in "$@"; do
    local id; id=$(ensure_pane "$ws" "$name")
    if is_up "$name"; then echo "$name: already up ($id)"; continue; fi
    if [ -n "$(pane_busy "$id")" ]; then herdr pane send-keys "$id" ctrl+c >/dev/null; sleep 1; fi
    herdr pane run "$id" "$(cmd_of "$name")" >/dev/null
    echo "$name: starting in pane $id"
  done
  for name in "$@"; do wait_up "$name" || true; done
}
herdr_down() {
  local ws; ws=$(ws_id); [ -n "$ws" ] || { for n in "$@"; do kill_hard "$n"; done; return; }
  for name in "$@"; do
    local id; id=$(pane_by_label "$ws" "$name")
    if [ -n "$id" ] && [ -n "$(pane_busy "$id")" ]; then herdr pane send-keys "$id" ctrl+c >/dev/null; fi
    wait_down "$name" 15 || { kill_hard "$name"; wait_down "$name" 5 || true; }
    is_up "$name" && echo "$name: still up" || echo "$name: stopped"
  done
}

# ── фон (вне herdr) ──────────────────────────────────────────────────────────
pid_alive() { local pid; pid=$(cat "$RUN/$1.pid" 2>/dev/null || true); [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; }
bg_up() {
  for name in "$@"; do
    if is_up "$name" || pid_alive "$name"; then echo "$name: already up"; continue; fi
    ( setsid bash -c "export LOG_FORMAT=json; $(cmd_of "$name")" >"$LOG/$name.log" 2>&1 & echo $! >"$RUN/$name.pid" )
    echo "$name: started (pid $(cat "$RUN/$name.pid")) → logs/dev/$name.log"
  done
  for name in "$@"; do wait_up "$name" || true; done
}
bg_down() {
  for name in "$@"; do
    if pid_alive "$name"; then local pid; pid=$(cat "$RUN/$name.pid"); kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; fi
    wait_down "$name" 15 || { kill_hard "$name"; wait_down "$name" 5 || true; }
    rm -f "$RUN/$name.pid"; is_up "$name" && echo "$name: still up" || echo "$name: stopped"
  done
}

action=${1:-status}; shift || true
names=${*:-$ALL}
in_herdr() { [ "${HERDR_ENV:-}" = 1 ] && command -v herdr >/dev/null; }
case "$action" in
  up)   if in_herdr; then herdr_up $names; else bg_up $names; fi
        echo "hub http://localhost:8081 · runner http://localhost:8082 · front http://localhost:5173" ;;
  down) if in_herdr; then herdr_down $names; else bg_down $names; fi ;;
  status) for name in $names; do is_up "$name" && echo "$name: up" || echo "$name: down"; done ;;
  *) echo "usage: $0 up|down|status [name…]" >&2; exit 2 ;;
esac
