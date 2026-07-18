#!/bin/bash
# Relay + Demo User A/B をまとめて起動する。Ctrl-Cで全プロセスを止める。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PIDS=""
mkdir -p "$ROOT_DIR/.tmp"
DEMO_ROOT="${ENISHI_DEMO_ROOT:-$(mktemp -d "$ROOT_DIR/.tmp/enishi-demo.XXXXXX")}"
export ENISHI_DEMO_ROOT="$DEMO_ROOT"

pick_port() {
  "${ENISHI_PYTHON:-$ROOT_DIR/.venv/bin/python}" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

export RELAY_PORT="${RELAY_PORT:-$(pick_port)}"
export ENISHI_DEMO_USER_A_PORT="${ENISHI_DEMO_USER_A_PORT:-$(pick_port)}"
export ENISHI_DEMO_USER_B_PORT="${ENISHI_DEMO_USER_B_PORT:-$(pick_port)}"
export ENISHI_DEMO_UI_PORT="${ENISHI_DEMO_UI_PORT:-$(pick_port)}"
export ENISHI_RELAY_URL="http://127.0.0.1:${RELAY_PORT}"
export ENISHI_ALLOWED_UI_ORIGIN="http://127.0.0.1:${ENISHI_DEMO_UI_PORT}"

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
echo "  Relay  http://127.0.0.1:${RELAY_PORT}"
echo "  User A http://127.0.0.1:${ENISHI_DEMO_USER_A_PORT} token demo-token-a"
echo "  User B http://127.0.0.1:${ENISHI_DEMO_USER_B_PORT} token demo-token-b"
echo "  Data   $DEMO_ROOT"

wait_for_health "Relay" "http://127.0.0.1:${RELAY_PORT}/health"
wait_for_health "User A" "http://127.0.0.1:${ENISHI_DEMO_USER_A_PORT}/health"
wait_for_health "User B" "http://127.0.0.1:${ENISHI_DEMO_USER_B_PORT}/health"

"${ENISHI_PYTHON:-$ROOT_DIR/.venv/bin/python}" "$ROOT_DIR/scripts/seed_demo.py"
"${ENISHI_PYTHON:-$ROOT_DIR/.venv/bin/python}" "$ROOT_DIR/scripts/verify_demo.py"

if [ "${ENISHI_DEMO_VERIFY_PAIRING:-0}" = "1" ]; then
  "${ENISHI_PYTHON:-$ROOT_DIR/.venv/bin/python}" "$ROOT_DIR/scripts/verify_pairing_e2e.py"
fi

if [ "${ENISHI_DEMO_EXIT_AFTER_VERIFY:-0}" = "1" ]; then
  exit 0
fi

if [ "${ENISHI_DEMO_UI:-0}" = "1" ]; then
  (
    cd "$ROOT_DIR/apps/desktop"
    VITE_CORE_PORT="$ENISHI_DEMO_USER_A_PORT" VITE_CORE_TOKEN=demo-token-a npm run dev -- --host 127.0.0.1 --port "$ENISHI_DEMO_UI_PORT" --strictPort
  ) &
  PIDS="$PIDS $!"
  wait_for_health "Demo UI" "http://127.0.0.1:${ENISHI_DEMO_UI_PORT}"
  echo ""
  echo "Demo UI is ready: http://127.0.0.1:${ENISHI_DEMO_UI_PORT}"
  echo "Open it in a browser and start with the pending approval."
  if [ "${ENISHI_DEMO_OPEN_BROWSER:-0}" = "1" ] && command -v open >/dev/null 2>&1; then
    open "http://127.0.0.1:${ENISHI_DEMO_UI_PORT}"
  fi
fi
wait
