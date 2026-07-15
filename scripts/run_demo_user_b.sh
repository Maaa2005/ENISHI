#!/bin/bash
# Demo User B のLocal Coreを独立DB・独立鍵で起動する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR/services/local-core"

DATA_DIR="$ROOT_DIR/.tmp/demo-user-b"
mkdir -p "$DATA_DIR/cache" "$DATA_DIR/logs"

export ENISHI_DATA_DIR="$DATA_DIR"
export ENISHI_CACHE_DIR="$DATA_DIR/cache"
export ENISHI_LOG_DIR="$DATA_DIR/logs"
export ENISHI_LOCAL_TOKEN="${ENISHI_LOCAL_TOKEN:-demo-token-b}"
export ENISHI_RELAY_URL="${ENISHI_RELAY_URL:-http://127.0.0.1:8870}"
export ENISHI_RELAY_TOKEN="${ENISHI_RELAY_TOKEN:-relay-token-b}"
PORT="${ENISHI_LOCAL_PORT:-8872}"

echo "ENISHI Demo User B: http://127.0.0.1:${PORT} (token: ${ENISHI_LOCAL_TOKEN})"
echo "data: ${DATA_DIR}"
exec uv run uvicorn enishi_core.main:app --host 127.0.0.1 --port "$PORT"
