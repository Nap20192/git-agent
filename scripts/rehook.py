"""Перепрописывает GitHub-хуки подключённых репозиториев на новый base-URL.

Запуск (из agent/, чтобы был venv): uv run python ../scripts/rehook.py https://…
Секрет и токен берутся из БД (расшифровка SECRETS_KEY). DNS-флап системного
resolved обходится резолвом api.github.com через 1.1.1.1.
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.getcwd())  # запускается из agent/ — корень python-проекта

import psycopg
from core.config import settings
from core.runner.crypto import decrypt

BASE = sys.argv[1].rstrip("/")


def gh_ip() -> str:
    out = subprocess.run(
        ["sh", "-c", "nslookup -type=A api.github.com 1.1.1.1 2>/dev/null"
         " | awk '/^Address: /{print $2}' | grep -E '^[0-9.]+$' | head -1"],
        capture_output=True, text=True,
    ).stdout.strip()
    return out


def curl(token: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    cmd = ["curl", "-s", "-m", "20", "-w", "\n%{http_code}",
           "--resolve", f"api.github.com:443:{gh_ip()}",
           "-X", method, f"https://api.github.com{path}",
           "-H", f"Authorization: Bearer {token}",
           "-H", "Accept: application/vnd.github+json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    payload, _, code = out.rpartition("\n")
    try:
        return int(code), json.loads(payload or "{}")
    except (ValueError, json.JSONDecodeError):
        return 0, {}


def main() -> None:
    with psycopg.connect(settings.database_url) as conn:
        rows = conn.execute("""
            SELECT r.id, r.owner, r.name, r.webhook_provider_id,
                   r.webhook_secret_enc, i.access_token_enc
            FROM hub.repositories r
            JOIN hub.identities i ON i.id = r.identity_id
            WHERE r.provider = 'github' AND r.webhook_provider_id IS NOT NULL
        """).fetchall()

    if not rows:
        print("нет подключённых github-репозиториев с хуками")
        return
    for repo_id, owner, name, hook_id, sec_enc, tok_enc in rows:
        token = decrypt(bytes(tok_enc), settings.secrets_key)
        secret = decrypt(bytes(sec_enc), settings.secrets_key) if sec_enc else None
        cfg = {"url": f"{BASE}/hooks/github/{repo_id}", "content_type": "json",
               "secret": secret, "insecure_ssl": "0"}
        code, resp = curl(token, "PATCH", f"/repos/{owner}/{name}/hooks/{hook_id}",
                          {"config": cfg, "events": ["*"], "active": True})
        ping, _ = curl(token, "POST", f"/repos/{owner}/{name}/hooks/{hook_id}/pings")
        status = "ok" if code == 200 and ping == 204 else f"PATCH={code} ping={ping}"
        print(f"{owner}/{name} (repo {repo_id}, hook {hook_id}): {status}"
              f" -> {resp.get('config', {}).get('url', '?')}")


if __name__ == "__main__":
    main()
