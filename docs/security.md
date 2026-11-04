> **Status: frozen (2026-10-23).** Describes the ENISHI app as implemented; no further updates. The protocol continues at https://github.com/Maaa2005/aun-protocol (`aun/0.3`).

# Security posture

Implemented so far:

- The Local Core listens on `127.0.0.1` only. Binding to `0.0.0.0` is disallowed.
- `/v1/*` requires a bearer token; Tauri generates a fresh token per session.
- Token comparison uses constant-time comparison (`secrets.compare_digest`).
- Child processes are launched as a command name plus an argument array — never a concatenated shell string.
- CLI detection is limited to `shutil.which` plus a `--version` probe. Credentials of other tools are never read.
- External-provider credentials are not stored by ENISHI. The Local Core bearer token exists only for the app session.
- Tauri-launched Local Core stores the node signing key in the macOS Keychain (`com.enishi.desktop`). Existing `0600` file keys are migrated on first launch and then removed. Standalone CLI demos retain the `0700` directory / `0600` file fallback.
- Human approval of negotiation outcomes is policy-based and differs by negotiation type; it is not applied to every agreement.
  - `meeting.schedule` (local and over the Relay) and `cost.split` run the shared guards (`domains/common.py`, `evaluate_common_guards`): delegation turned off, clone confidence below 0.6 (`CONFIDENCE_THRESHOLD`), or a per-peer relationship rule with `allow_auto_accept: false` stop for approval. Each domain adds its own conditions (for example meeting time preferences, cost limits). Otherwise they may agree automatically.
  - `task.request` (local only, `supports_remote = False`) does **not** check confidence or relationship rules. With the default limits it agrees automatically, without approval, for requests up to 2 hours with a deadline at least 1 day away (`domains/task_request.py`); it counters up to 4 hours; it stops for approval above that or when `task_negotiation` delegation is off. Confidence 0.3 still auto-agrees within those limits.
  - Activating a clone raises its confidence to at least 0.6 (`services/clones.py`), so the confidence check only fires if confidence drops afterwards.
  - Coding tasks are gated only by self-declared operations; see "Known limitations" below.
- Negotiation messages are signed (Ed25519, RFC 8785 canonical JSON), so the receiver can verify the sender and detect tampering.
- The Local Core is terminated when the app exits, leaving no orphan process.

## Relay deployment boundary

- Demo mode may use `RELAY_NODE_TOKENS` with plaintext credentials inside an isolated local environment.
- Production mode sets `RELAY_REQUIRE_HASHED_TOKENS=true`; startup then fails closed if plaintext credentials are configured or no valid SHA-256 credentials exist.
- The Relay hashes the presented bearer token and compares every configured digest with `secrets.compare_digest`. A credential cannot be assigned to two node identities.
- Multiple digests may map to the same node during rotation. Remove the old digest only after the node has switched to the new token.
- Relay startup output includes node identities but never bearer tokens. Delivery logs contain message ID, sender, receiver, and byte size, but no payload, token, or digest.
- The bearer token must have high entropy. `python -m relay.token_tool --generate` creates a 256-bit token and prints the plaintext only for client provisioning.
- Internet-facing deployments must terminate TLS at a managed reverse proxy or load balancer and keep the Relay HTTP listener on a private interface. The reference Docker deployment uses Caddy for automatic certificates, publishes only 80/443, blocks public `/metrics`, and leaves Relay port 8080 on an internal network. The local demo launcher intentionally remains HTTP-only on loopback.
- `/health` reports liveness without touching storage. `/ready` fails with `503` if the SQLite mailbox cannot start a write transaction and read its table. Error responses do not include the storage exception.
- Prometheus metrics contain aggregate delivery, fetch, acknowledgement, rejection, readiness, uptime, and pending counts only. They do not use node IDs, message IDs, credentials, hashes, or envelope fields as labels.

## Known limitations

- **No end-to-end encryption.** Envelopes are signed but not encrypted. They travel over TLS in the reference deployment, but the Relay stores them as plaintext JSON (`services/relay/relay/store.py`) and can read negotiation contents. "Untrusted Relay" here means it cannot forge or alter messages undetected, not that it cannot read them.
- **The coding-task approval gate is not a security boundary.**
  - Approval is triggered only by the task's self-declared `requested_operations` (`services/local-core/enishi_core/services/tasks.py`). Nothing inspects what the provider actually does.
  - The desktop UI always sends `requested_operations: []` (`apps/desktop/src/pages/TasksPage.tsx`), so UI-created tasks are never stopped for approval.
  - Codex runs with `--sandbox workspace-write` (`providers/codex.py`); the Claude Code adapter passes `--add-dir` only.
  - Without a project, the working directory is the Local Core's current directory.
  - The prohibited-action list in the clone context package is an instruction to the provider, not enforcement.
- **Remote approval flow.** `REQUEST_APPROVAL`, `APPROVAL_RESULT`, `EXECUTE` and `RECEIPT` are never sent between nodes and are rejected on receive (`services/protocol_state.py`). Human approval is a local step before `ACCEPT` is sent.
- **Legacy `aun/0.1` receive path** skips receiver node binding (`services/remote_negotiation.py`).
- **Tauri CSP is `null`** (`apps/desktop/src-tauri/tauri.conf.json`).
- **macOS only.** Windows and Linux are not supported.
