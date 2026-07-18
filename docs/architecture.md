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
       │ signed and encrypted AUN messages
       ▼
Forward-only Relay (hashed bearer auth, SQLite mailbox, TTL, destination authz)
       ▼
Peer Local Core
```

- Tauri launches Local Core as a child process and terminates it when the app exits.
- `/v1/*` requires a bearer token; Local Core accepts loopback traffic only.
- Each person has a stable personal-agent identity distinct from the node transport identity.
- Peers exchange signed AUN Protocol messages through the relay. Raw memories and calendars stay local.
- The Relay persists only pending signed/encrypted envelopes and delivery metadata. An acknowledgement removes a delivery, while TTL expiry removes abandoned deliveries; decision state remains local.
- Production Relay configuration stores only bearer-token SHA-256 digests. Verification is constant-time, and overlapping digests for one node permit credential rotation without downtime.
- Relationship and risk policies decide whether a proposed result can proceed or must stop at human approval.
- Coding tasks use a project-scoped context package and an explicit permission set. High-risk operations are denied or require approval.
- Audit APIs expose allow-listed metadata only; tokens, key material, and memory bodies are excluded.

The presentation launcher runs two independent Local Cores and one Relay, seeds a trusted peer relationship, and leaves a real remote negotiation waiting for approval on the presenter's node.
