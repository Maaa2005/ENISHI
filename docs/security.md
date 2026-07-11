# Security posture

Implemented so far:

- The Local Core listens on `127.0.0.1` only. Binding to `0.0.0.0` is disallowed.
- `/v1/*` requires a bearer token; Tauri generates a fresh token per session.
- Token comparison uses constant-time comparison (`secrets.compare_digest`).
- Child processes are launched as a command name plus an argument array — never a concatenated shell string.
- CLI detection is limited to `shutil.which` plus a `--version` probe. Credentials of other tools are never read.
- Secrets are not written to SQLite or JSON. They go to the macOS Keychain (`com.twinlink.desktop`); this is wired up in Phase 5.
- The Local Core is terminated when the app exits, leaving no orphan process.
