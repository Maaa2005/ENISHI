# Security posture

Implemented so far:

- The Local Core listens on `127.0.0.1` only. Binding to `0.0.0.0` is disallowed.
- `/v1/*` requires a bearer token; Tauri generates a fresh token per session.
- Token comparison uses constant-time comparison (`secrets.compare_digest`).
- Child processes are launched as a command name plus an argument array — never a concatenated shell string.
- CLI detection is limited to `shutil.which` plus a `--version` probe. Credentials of other tools are never read.
- External-provider credentials are not stored by ENISHI. The Local Core bearer token exists only for the app session.
- Tauri-launched Local Core stores the node signing key in the macOS Keychain (`com.enishi.desktop`). Existing `0600` file keys are migrated on first launch and then removed. Standalone CLI demos retain the `0700` directory / `0600` file fallback.
- Human approval is risk-based: destructive and externally visible actions require approval, while explicitly delegated low-risk negotiations may complete automatically under the configured policy.
- The Local Core is terminated when the app exits, leaving no orphan process.

## Relay deployment boundary

- Demo mode may use `RELAY_NODE_TOKENS` with plaintext credentials inside an isolated local environment.
- Production mode sets `RELAY_REQUIRE_HASHED_TOKENS=true`; startup then fails closed if plaintext credentials are configured or no valid SHA-256 credentials exist.
- The Relay hashes the presented bearer token and compares every configured digest with `secrets.compare_digest`. A credential cannot be assigned to two node identities.
- Multiple digests may map to the same node during rotation. Remove the old digest only after the node has switched to the new token.
- Relay startup output includes node identities but never bearer tokens. Delivery logs contain message ID, sender, receiver, and byte size, but no payload, token, or digest.
- The bearer token must have high entropy. `python -m relay.token_tool --generate` creates a 256-bit token and prints the plaintext only for client provisioning.
- Internet-facing deployments must terminate TLS at a managed reverse proxy or load balancer and keep the Relay HTTP listener on a private interface. TLS enforcement and certificate lifecycle belong to that deployment boundary and are not provided by the demo launcher.
