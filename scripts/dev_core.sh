#!/bin/bash
# Local Coreを単体起動する（ブラウザ開発・API確認用）
set -eu
cd "$(dirname "$0")/../services/local-core"

export TWINLINK_LOCAL_TOKEN="${TWINLINK_LOCAL_TOKEN:-dev-local-token}"
PORT="${TWINLINK_LOCAL_PORT:-8765}"

echo "ENISHI Local Core: http://127.0.0.1:${PORT} (token: ${TWINLINK_LOCAL_TOKEN})"
exec uv run uvicorn twinlink_core.main:app --host 127.0.0.1 --port "$PORT"
