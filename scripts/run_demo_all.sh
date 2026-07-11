#!/bin/bash
# Relay + Demo User A/B をまとめて起動する。Ctrl-Cで全プロセスを止める。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PIDS=""

cleanup() {
  for pid in $PIDS; do
    kill "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

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
wait
