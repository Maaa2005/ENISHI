#!/bin/bash
# Demo User A のLocal Coreを独立DB・独立鍵で起動する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR/services/local-core"

DEMO_ROOT="${ENISHI_DEMO_ROOT:-$ROOT_DIR/.tmp/demo-current}"
PYTHON="${ENISHI_PYTHON:-$ROOT_DIR/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  echo "Demo Python not found: $PYTHON" >&2
  echo "Run 'uv sync --all-packages' in $ROOT_DIR first." >&2
  exit 1
fi

DATA_DIR="$DEMO_ROOT/user-a"
mkdir -p "$DATA_DIR/cache" "$DATA_DIR/logs"

export ENISHI_DATA_DIR="$DATA_DIR"
export ENISHI_CACHE_DIR="$DATA_DIR/cache"
export ENISHI_LOG_DIR="$DATA_DIR/logs"
export ENISHI_LOCAL_TOKEN="${ENISHI_LOCAL_TOKEN:-demo-token-a}"
export ENISHI_RELAY_URL="${ENISHI_RELAY_URL:-http://127.0.0.1:8870}"
export ENISHI_RELAY_TOKEN="${ENISHI_RELAY_TOKEN:-relay-token-a}"
PORT="${ENISHI_DEMO_USER_A_PORT:-${ENISHI_LOCAL_PORT:-8871}}"

echo "ENISHI Demo User A: http://127.0.0.1:${PORT} (token: ${ENISHI_LOCAL_TOKEN})"
echo "data: ${DATA_DIR}"
exec "$PYTHON" -m uvicorn enishi_core.main:app --host 127.0.0.1 --port "$PORT" --log-level warning
