#!/bin/bash
# 2ノードデモ用Relayを独立データディレクトリで起動する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEMO_ROOT="${ENISHI_DEMO_ROOT:-$ROOT_DIR/.tmp/demo-current}"
PYTHON="${ENISHI_PYTHON:-$ROOT_DIR/.venv/bin/python}"

if [ ! -x "$PYTHON" ]; then
  echo "Demo Python not found: $PYTHON" >&2
  echo "Run 'uv sync --all-packages' in $ROOT_DIR first." >&2
  exit 1
fi

mkdir -p "$DEMO_ROOT/relay"
mkdir -p "$DEMO_ROOT/user-a" "$DEMO_ROOT/user-b"

agent_id_for() {
  local data_dir="$1"
  cd "$ROOT_DIR/services/local-core"
  ENISHI_DATA_DIR="$data_dir" "$PYTHON" -c 'from pathlib import Path; from enishi_core.security.keys import ensure_node_keypair; import os; print(ensure_node_keypair(Path(os.environ["ENISHI_DATA_DIR"]))[0].agent_id)'
}

AGENT_A="$(agent_id_for "$DEMO_ROOT/user-a")"
AGENT_B="$(agent_id_for "$DEMO_ROOT/user-b")"

cd "$ROOT_DIR/services/relay"

export RELAY_NODE_TOKENS="${RELAY_NODE_TOKENS:-${AGENT_A}=relay-token-a,${AGENT_B}=relay-token-b}"
export RELAY_MESSAGE_TTL_SECONDS="${RELAY_MESSAGE_TTL_SECONDS:-3600}"
export RELAY_RATE_LIMIT_PER_MINUTE="${RELAY_RATE_LIMIT_PER_MINUTE:-120}"
PORT="${RELAY_PORT:-8870}"

echo "ENISHI Relay demo: http://127.0.0.1:${PORT}"
echo "agents: ${RELAY_NODE_TOKENS}"
exec "$PYTHON" -m uvicorn relay.main:app --host 127.0.0.1 --port "$PORT" --log-level warning
