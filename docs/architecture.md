# アーキテクチャ

全体像は [twinlink.md §6](../twinlink.md) を正とする。

## 現状（Phase 0–2）

```
TwinLink Desktop (Tauri 2 + React + TS)
  └─ get_core_connection (Tauri Command)
       │ ランダムポート + ランダムトークン
       ▼
TwinLink Local Core (FastAPI, 127.0.0.1限定)
  ├─ /health
  └─ /v1/*（Bearer認証必須）
       └─ SQLite (~/Library/Application Support/TwinLink/twinlink.db)
```

- TauriがLocal Coreを子プロセスとして起動し、終了時にkillする（`src-tauri/src/process/`）
- 認証トークンは起動ごとに生成し、環境変数 `TWINLINK_LOCAL_TOKEN` で渡す
- モデル: `User` / `CloneAgent`（twinlink.md §17–18。MemoryItem等はPhase 2後半で追加）
