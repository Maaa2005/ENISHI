# Security posture

Implemented so far:

- The Local Core listens on `127.0.0.1` only. Binding to `0.0.0.0` is disallowed.
- `/v1/*` requires a bearer token; Tauri generates a fresh token per session.
- Token comparison uses constant-time comparison (`secrets.compare_digest`).
- Child processes are launched as a command name plus an argument array — never a concatenated shell string.
- CLI detection is limited to `shutil.which` plus a `--version` probe. Credentials of other tools are never read.
- External-provider credentials are not stored by ENISHI. The Local Core bearer token exists only for the app session.
- The node signing key is currently stored under the Local Core data directory with directory mode `0700` and file mode `0600`. Moving it to the macOS Keychain (`com.twinlink.desktop`) remains packaging work.
- Human approval is risk-based: destructive and externally visible actions require approval, while explicitly delegated low-risk negotiations may complete automatically under the configured policy.
- The Local Core is terminated when the app exits, leaving no orphan process.
