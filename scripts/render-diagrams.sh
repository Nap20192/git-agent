#!/usr/bin/env bash
# Рендер sequence-диаграмм из docs/flows.md в docs/flows/N.png (mermaid-cli + системный Chrome).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p docs/flows
python3 - <<'EOF'
import re, pathlib
md = pathlib.Path('docs/flows.md').read_text()
for n, _t, body in re.findall(r'## (\d+)\. ([^\n]+)\n\n```mermaid\n(.*?)```', md, re.S):
    pathlib.Path(f'docs/flows/{n}.mmd').write_text(body)
EOF
PPTR=$(mktemp); printf '{"executablePath":"%s","args":["--no-sandbox"]}' "${CHROME:-/usr/bin/google-chrome-stable}" > "$PPTR"
cd frontend
for f in ../docs/flows/*.mmd; do
  bunx --yes @mermaid-js/mermaid-cli -p "$PPTR" -i "$f" -o "${f%.mmd}.png" -w 1800 -b white >/dev/null 2>&1 \
    && echo "ok   $(basename "$f")" || echo "FAIL $(basename "$f")"
done
rm -f "$PPTR"
