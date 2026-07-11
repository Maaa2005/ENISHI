# TwinLink Desktop for macOS

本人代理型AIエージェント同士が構造化データで通信するためのプラットフォーム。
仕様は [twinlink.md](twinlink.md) を参照。

## 構成

- `apps/desktop/` — Tauri 2 + React + TypeScript のデスクトップアプリ
- `services/local-core/` — Python (FastAPI) の Local Core。127.0.0.1限定で待ち受け、Bearerトークン認証必須
- `scripts/` — 環境確認・開発用スクリプト

## 必要環境

- macOS 13 Ventura以上（Apple Silicon / Intel）
- Node.js 20以上・npm
- Python 3.12以上・[uv](https://docs.astral.sh/uv/)
- Rust（Tauriのビルドに必要。https://rustup.rs から導入）
- Xcode Command Line Tools（`xcode-select --install`）

環境確認:

```bash
./scripts/check_macos_env.sh
```

## セットアップ

```bash
npm install                      # フロントエンド依存
cd services/local-core && uv sync --group dev   # Python依存
```

## 起動

### デスクトップアプリ（Rust導入後）

```bash
./scripts/dev_desktop.sh
# または
cd apps/desktop && npm run tauri dev
```

TauriがLocal Coreをランダムポート＋ランダムトークンで自動起動し、
アプリ終了時にプロセスも終了する。

### Local Core単体（API開発・ブラウザ確認用）

```bash
./scripts/dev_core.sh            # http://127.0.0.1:8765
npm run dev                      # Vite (http://localhost:5173)
```

ブラウザ開発時の接続先は `VITE_CORE_PORT` / `VITE_CORE_TOKEN` で指定
（既定: 8765 / dev-local-token。`.env.example` 参照）。

## テスト

```bash
# Python
cd services/local-core && uv run --group dev pytest
uv run --group dev ruff check . && uv run --group dev mypy twinlink_core

# TypeScript
npm run test && npm run typecheck

# Rust（Rust導入後）
cd apps/desktop/src-tauri && cargo test
```

## データ保存場所

- アプリデータ: `~/Library/Application Support/TwinLink/`（SQLite `twinlink.db`）
- キャッシュ: `~/Library/Caches/TwinLink/`
- ログ: `~/Library/Logs/TwinLink/`
- 秘密情報: macOS Keychain（サービス名 `com.twinlink.desktop`）— ファイル保存禁止

## 現在の実装状況

Phase 0（環境確認）・Phase 1（デスクトップシェル + Local Core起動）・
Phase 2の基本モデル（User / CloneAgent）まで実装済み。
詳細なフェーズ計画は twinlink.md §35 を参照。
