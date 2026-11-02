> **Status: frozen (2026-10-23).** This describes the ENISHI app as implemented (`aun/0.1`–`0.2`). The protocol continues at https://github.com/Maaa2005/aun-protocol (`aun/0.3`).

# Architecture

## Current presentation architecture

```
ENISHI Desktop (Tauri 2 + React + TypeScript)
  └─ random loopback port + per-session bearer token
       ▼
ENISHI Local Core (FastAPI, 127.0.0.1 only)
  ├─ users, memories, clones, projects, tasks
  ├─ negotiations, approvals, agreements, audit events
  ├─ provider adapters (Codex / Claude Code / mock)
  └─ SQLite
       │ signed AUN messages (TLS in transit; not end-to-end encrypted)
       ▼
TLS proxy (Caddy; public HTTPS, blocks public metrics)
       ▼
Forward-only Relay (private network, hashed auth, SQLite mailbox, TTL)
       ▼
Peer Local Core
```

- Tauri launches Local Core as a child process and terminates it when the app exits.
- `/v1/*` requires a bearer token; Local Core accepts loopback traffic only.
- Each person has a stable personal-agent identity distinct from the node transport identity.
- Peers exchange signed AUN Protocol messages through the relay. Raw memories and calendars stay local.
- The Relay persists only pending signed envelopes and delivery metadata. Envelopes are stored as plaintext JSON (`services/relay/relay/store.py`): signatures give authenticity and tamper detection, TLS protects the transport, but there is no end-to-end encryption, so the Relay can read negotiation contents. An acknowledgement removes a delivery, while TTL expiry removes abandoned deliveries; decision state remains local.
- Production Relay configuration stores only bearer-token SHA-256 digests. Verification is constant-time, and overlapping digests for one node permit credential rotation without downtime.
- `/health` is process liveness; `/ready` additionally verifies a SQLite write transaction and mailbox read. `/metrics` exposes aggregate counters without node, message, credential, or envelope labels.
- The reference deployment exposes only Caddy. Relay port 8080 and Prometheus metrics remain on an internal Docker network.
- Delegation, confidence, relationship, and domain policies decide whether a proposed result is agreed automatically or must stop at human approval. The confidence check applies to `meeting.schedule` and `cost.split` but not to `task.request`, which decides from its hour and deadline limits only (README, "When approval happens").
- Coding tasks use a project-scoped context package and an explicit permission set. Level-3 operations (for example `git_push`, `rm_rf`) are rejected and Level-2 operations (for example `delete_files`, `install_dependencies`) wait for approval, but only when the task itself lists them in `requested_operations`. The Core does not detect operations at execution time, and the desktop UI always sends an empty list. See "Known limitations" in the README and `security.md`.
- Audit APIs expose allow-listed metadata only; tokens, key material, and memory bodies are excluded.

The presentation launcher runs two independent Local Cores and one Relay, seeds a trusted peer relationship, and leaves a real remote negotiation waiting for approval on the presenter's node.
