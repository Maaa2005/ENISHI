# Architecture

## Current state (Phase 0–2)

```
TwinLink Desktop (Tauri 2 + React + TS)
  └─ get_core_connection (Tauri command)
       │ random port + random token
       ▼
TwinLink Local Core (FastAPI, 127.0.0.1 only)
  ├─ /health
  └─ /v1/*  (bearer auth required)
       └─ SQLite (~/Library/Application Support/TwinLink/twinlink.db)
```

- Tauri launches the Local Core as a child process and kills it on exit (`src-tauri/src/process/`).
- The auth token is generated per session and passed to the Local Core via the `TWINLINK_LOCAL_TOKEN` environment variable.
- Core models: `User` and `CloneAgent`. `MemoryItem` and related models are added in the Phase 2 back half.
