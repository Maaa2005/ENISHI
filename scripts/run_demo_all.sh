#!/bin/bash
# Relay + Demo User A/B をまとめて起動する。Ctrl-Cで全プロセスを止める。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PIDS=""
mkdir -p "$ROOT_DIR/.tmp"
DEMO_ROOT="${ENISHI_DEMO_ROOT:-$(mktemp -d "$ROOT_DIR/.tmp/enishi-demo.XXXXXX")}"
export ENISHI_DEMO_ROOT="$DEMO_ROOT"

cleanup() {
  for pid in $PIDS; do
    kill "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

wait_for_health() {
  local name="$1"
  local url="$2"
  local attempts=0
  while [ "$attempts" -lt 80 ]; do
    if curl --fail --silent "$url" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 0.25
  done
  echo "$name did not become ready: $url" >&2
  return 1
}

"$ROOT_DIR/scripts/run_demo_relay.sh" &
PIDS="$PIDS $!"
sleep 1
"$ROOT_DIR/scripts/run_demo_user_a.sh" &
PIDS="$PIDS $!"
"$ROOT_DIR/scripts/run_demo_user_b.sh" &
PIDS="$PIDS $!"

echo "Demo processes started:"
echo "  Relay  http://127.0.0.1:8870"
echo "  User A http://127.0.0.1:8871 token demo-token-a"
echo "  User B http://127.0.0.1:8872 token demo-token-b"
echo "  Data   $DEMO_ROOT"

wait_for_health "Relay" "http://127.0.0.1:8870/health"
wait_for_health "User A" "http://127.0.0.1:8871/health"
wait_for_health "User B" "http://127.0.0.1:8872/health"

"${ENISHI_PYTHON:-$ROOT_DIR/.venv/bin/python}" "$ROOT_DIR/scripts/seed_demo.py"

if [ "${ENISHI_DEMO_UI:-0}" = "1" ]; then
  (
    cd "$ROOT_DIR/apps/desktop"
    VITE_CORE_PORT=8871 VITE_CORE_TOKEN=demo-token-a npm run dev -- --host 127.0.0.1
  ) &
  PIDS="$PIDS $!"
  wait_for_health "Demo UI" "http://127.0.0.1:5173"
  echo ""
  echo "Demo UI is ready: http://127.0.0.1:5173"
  echo "Open it in a browser and start with the pending approval."
fi
wait
