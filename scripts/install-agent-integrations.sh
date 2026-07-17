#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
server="$repo_root/.venv/bin/enishi-memory-mcp"
control_server="$repo_root/.venv/bin/enishi-mcp"

if [ ! -x "$server" ] || [ ! -x "$control_server" ]; then
  echo "MCP server is not installed. Run: cd '$repo_root/services/local-core' && uv sync" >&2
  exit 1
fi

if command -v codex >/dev/null 2>&1; then
  codex mcp remove enishi >/dev/null 2>&1 || true
  codex mcp add enishi -- "$control_server"
  codex mcp remove enishi-memory >/dev/null 2>&1 || true
  codex mcp add enishi-memory -- "$server"
fi

if command -v claude >/dev/null 2>&1; then
  claude mcp remove enishi -s user >/dev/null 2>&1 || true
  claude mcp add --scope user enishi -- "$control_server"
  claude mcp remove enishi-memory -s user >/dev/null 2>&1 || true
  claude mcp add --scope user enishi-memory -- "$server"
fi

echo "ENISHI control and memory MCP registration completed."
