#!/bin/bash
# 2ノードデモ用Relayを独立データディレクトリで起動する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT_DIR/.tmp/demo-relay"
mkdir -p "$ROOT_DIR/.tmp/demo-user-a" "$ROOT_DIR/.tmp/demo-user-b"

agent_id_for() {
  local data_dir="$1"
  cd "$ROOT_DIR/services/local-core"
  ENISHI_DATA_DIR="$data_dir" uv run python -c 'from pathlib import Path; from enishi_core.security.keys import ensure_node_keypair; import os; print(ensure_node_keypair(Path(os.environ["ENISHI_DATA_DIR"]))[0].agent_id)'
}

AGENT_A="$(agent_id_for "$ROOT_DIR/.tmp/demo-user-a")"
AGENT_B="$(agent_id_for "$ROOT_DIR/.tmp/demo-user-b")"

cd "$ROOT_DIR/services/relay"

export RELAY_NODE_TOKENS="${RELAY_NODE_TOKENS:-${AGENT_A}=relay-token-a,${AGENT_B}=relay-token-b}"
export RELAY_MESSAGE_TTL_SECONDS="${RELAY_MESSAGE_TTL_SECONDS:-3600}"
export RELAY_RATE_LIMIT_PER_MINUTE="${RELAY_RATE_LIMIT_PER_MINUTE:-120}"
PORT="${RELAY_PORT:-8870}"

echo "ENISHI Relay demo: http://127.0.0.1:${PORT}"
echo "agents: ${RELAY_NODE_TOKENS}"
exec uv run uvicorn relay.main:app --host 127.0.0.1 --port "$PORT"
