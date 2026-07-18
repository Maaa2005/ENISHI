#!/bin/bash
# UIを開かず、署名付き名刺交換から両ノード合意までを実起動で検証する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export ENISHI_DEMO_VERIFY_PAIRING=1
export ENISHI_DEMO_EXIT_AFTER_VERIFY=1
exec "$ROOT_DIR/scripts/run_demo_all.sh"
