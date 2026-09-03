#!/usr/bin/env sh
# Проверка формальной модели рантайма. Требует lean 4 (elan).
# Использование: formal/check.sh
set -e
[ -x "$HOME/.elan/bin/lean" ] && PATH="$HOME/.elan/bin:$PATH"
cd "$(dirname "$0")"
lean RuntimeCore.lean && echo "RuntimeCore.lean: verified"
