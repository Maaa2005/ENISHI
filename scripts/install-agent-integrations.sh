#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
server="$repo_root/.venv/bin/enishi-memory-mcp"
control_server="$repo_root/.venv/bin/enishi-mcp"
user_bin_dir="${ENISHI_USER_BIN_DIR:-${HOME:?}/.local/bin}"

if [ ! -x "$server" ] || [ ! -x "$control_server" ]; then
  echo "MCP server is not installed. Run: cd '$repo_root/services/local-core' && uv sync" >&2
  exit 1
fi

# Plugin提供の.mcp.jsonからも解決できる安定したユーザーPATHを用意する。
mkdir -p "$user_bin_dir"
ln -sf "$control_server" "$user_bin_dir/enishi-mcp"
ln -sf "$server" "$user_bin_dir/enishi-memory-mcp"

if command -v codex >/dev/null 2>&1; then
  if codex plugin list 2>/dev/null | grep -q '^enishi@personal.*installed'; then
    # Pluginに同じMCPが含まれるため、Codexの二重登録を避ける。
    codex mcp remove enishi >/dev/null 2>&1 || true
    codex mcp remove enishi-memory >/dev/null 2>&1 || true
  else
    codex mcp remove enishi >/dev/null 2>&1 || true
    codex mcp add enishi -- "$control_server"
    codex mcp remove enishi-memory >/dev/null 2>&1 || true
    codex mcp add enishi-memory -- "$server"
  fi
fi

if command -v claude >/dev/null 2>&1; then
  claude mcp remove enishi -s user >/dev/null 2>&1 || true
  claude mcp add --scope user enishi -- "$control_server"
  claude mcp remove enishi-memory -s user >/dev/null 2>&1 || true
  claude mcp add --scope user enishi-memory -- "$server"
fi

echo "ENISHI control and memory MCP registration completed."
