#!/bin/bash
# TwinLink macOS環境確認スクリプト（twinlink.md §5）
# 不足ツールを検出して表示する。インストールは行わない。
set -u

MISSING=()

ok()   { printf "  ✓ %s\n" "$1"; }
ng()   { printf "  ✗ %s\n" "$1"; MISSING+=("$2"); }

echo "TwinLink macOS環境確認"
echo "======================"

# macOSバージョン
if command -v sw_vers >/dev/null 2>&1; then
  PRODUCT_VERSION=$(sw_vers -productVersion)
  MAJOR=${PRODUCT_VERSION%%.*}
  if [ "$MAJOR" -ge 13 ]; then
    ok "macOS ${PRODUCT_VERSION}（要件: 13 Ventura以上）"
  else
    ng "macOS ${PRODUCT_VERSION} は未対応（13 Ventura以上が必要）" "macOS 13+"
  fi
else
  ng "macOSではありません" "macOS"
fi

# CPUアーキテクチャ
ARCH=$(uname -m)
case "$ARCH" in
  arm64)  ok "CPU: Apple Silicon (arm64)" ;;
  x86_64) ok "CPU: Intel Mac (x86_64)" ;;
  *)      ng "CPU: 未知のアーキテクチャ (${ARCH})" "supported CPU" ;;
esac

# Xcode Command Line Tools
if xcode-select -p >/dev/null 2>&1; then
  ok "Xcode Command Line Tools: $(xcode-select -p)"
else
  ng "Xcode Command Line Tools 未検出（xcode-select --install で導入可能）" "Xcode Command Line Tools"
fi

# 各ツール
check_tool() {
  local label="$1" cmd="$2" version_flag="${3:---version}"
  if command -v "$cmd" >/dev/null 2>&1; then
    local ver
    ver=$("$cmd" "$version_flag" 2>/dev/null | head -1)
    ok "${label}: ${ver:-detected}"
  else
    ng "${label} 未検出" "$label"
  fi
}

check_tool "Rust" rustc
check_tool "Cargo" cargo
check_tool "Node.js" node
check_tool "npm" npm
check_tool "Python" python3
check_tool "Git" git
check_tool "SQLite" sqlite3

# Codex / Claude Code は任意（無くてもMockモードで動作）
if command -v codex >/dev/null 2>&1; then
  ok "Codex CLI: $(codex --version 2>/dev/null | head -1)"
else
  printf "  - Codex CLI 未検出（任意。Mockモードで動作可能）\n"
fi

if command -v claude >/dev/null 2>&1; then
  ok "Claude Code CLI: $(claude --version 2>/dev/null | head -1)"
else
  printf "  - Claude Code CLI 未検出（任意。Mockモードで動作可能）\n"
fi

# シェル
ok "利用可能なシェル: ${SHELL:-unknown}"

echo ""
if [ ${#MISSING[@]} -gt 0 ]; then
  echo "不足している開発ツール："
  for m in "${MISSING[@]}"; do
    echo "・${m}"
  done
  echo ""
  echo "実装を続ける前にインストールが必要です。"
  exit 1
else
  echo "必須ツールはすべて揃っています。"
fi
