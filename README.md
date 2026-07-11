# ENISHI (縁) — Personal AI Agents that Negotiate on Your Behalf

*An agent-to-agent negotiation and scheduling platform for macOS. Your personal AI agent talks to other people's agents over a structured protocol, shares only what's needed, and never acts without your approval.*

A communication platform for AI agents that act on your behalf. Instead of two people going back and forth to schedule a meeting or agree on terms, each person's delegated agent negotiates with the other over the **AUN Protocol** — and nothing gets executed until the human approves.

ENISHI is a macOS desktop app I'm building as a personal project. This repo is the working codebase; the detailed internal design spec is kept private.

> **The names.** *Enishi* (縁) is the bond that forms between people. *Aun* (阿吽) comes from *a-un no kokyū* — the wordless, in-and-out breathing of two people who move in perfect sync. That is exactly what two delegated agents are meant to do: reach an understanding on their principals' behalf without either side having to spell everything out.

## Why I'm building this

Coordination is expensive. Picking a meeting time across busy calendars, or settling small terms between two parties, eats real time and attention even though the decision itself is trivial. Handing that off to an AI assistant sounds obvious, but two problems make it hard to trust:

1. **Privacy.** To negotiate a time, your agent has to reason over your calendar — but the other side should never see your raw schedule, only whether a proposed slot works.
2. **Control.** An agent that can act for you is also an agent that can commit you to things you didn't want. There has to be a hard gate where a human signs off before anything real happens.

ENISHI is my attempt to build the plumbing for delegated agents that negotiate *without* leaking their principal's data and *without* acting without consent.

## How it works

Each user runs a local node. Two nodes talk through a relay that only forwards messages — it never sees decrypted content or makes decisions.

```
  User A's Mac                    User B's Mac
┌──────────────────┐          ┌──────────────────┐
│  ENISHI Desktop  │          │  ENISHI Desktop  │
│ (Tauri 2 + React)│          │ (Tauri 2 + React)│
│        │         │          │        │         │
│  random port +   │          │  random port +   │
│  random token    │          │  random token    │
│        ▼         │          │        ▼         │
│  Local Core      │          │  Local Core      │
│  (FastAPI,       │          │  (FastAPI,       │
│   127.0.0.1 only)│          │   127.0.0.1 only)│
│   └─ SQLite      │          │   └─ SQLite      │
└────────┬─────────┘          └─────────┬────────┘
         │                              │
         └──────────► Relay ◄───────────┘
              (forward-only: TTL,
               destination authz,
               size/rate limits,
               minimal logging)
```

The desktop app (Tauri 2 + React + TypeScript) is just the UI. The real work happens in the **Local Core**, a FastAPI service that binds to `127.0.0.1` only. Tauri launches it as a child process with a random port and a random bearer token per session, and kills it on exit so no orphan process is left listening. Every `/v1/*` route requires that token.

## The AUN Protocol

Agents exchange structured messages, not free text. Each message has a typed `message_type`:

`REQUEST` → `PROPOSE` → `COUNTER` → `ACCEPT` / `REJECT` → `REQUEST_APPROVAL` → `APPROVAL_RESULT` → `EXECUTE` → `RECEIPT`, plus `ERROR`.

A negotiation is a state machine over these messages. Proposals and counter-proposals are exchanged as deltas rather than full state, so a round of haggling stays small. The schemas live in `packages/protocol/` as JSON Schema, shared between both sides.

## Delegation, selective disclosure, and the human gate

Three ideas do the heavy lifting:

- **Clone agents.** When you delegate a task, ENISHI spins up a scoped agent (a "clone"). It starts in `review_required` state and cannot perform any high-privilege action until you explicitly activate it. The default profile denies destructive operations outright.
- **Selective disclosure.** You configure, per peer, what your agent is allowed to reveal. A negotiating agent answers "does this slot work?" without ever transmitting the underlying calendar. Memories marked `secret` never leave the device and are never packed into a clone's context.
- **Approval gate with expiry.** Before anything is executed, the protocol routes a `REQUEST_APPROVAL` to the human. Approvals carry an `expires_at`; once expired, the action can no longer run, so a stale "yes" from last week can't be replayed into an action today.

## Security design

The threat model assumes the relay is untrusted and the other agent may be adversarial. Some of the concrete decisions:

- Local Core listens on `127.0.0.1` only — binding to `0.0.0.0` is explicitly disallowed.
- Bearer token comparison uses constant-time comparison (`secrets.compare_digest`) to avoid timing leaks.
- The app never builds shell command strings. External CLIs are invoked as a command name plus a validated argument array, never a concatenated string.
- CLI detection is limited to `shutil.which` plus a `--version` probe. ENISHI never reads another tool's credentials.
- Secrets go to the macOS Keychain, never to SQLite or JSON on disk.

More detail is in [`docs/security.md`](docs/security.md).

## Status

Under active development. The core negotiation loop, node identity, selective disclosure, the clone lifecycle, the relay, and the human-approval gate are implemented and demoable across two local nodes plus a relay (see [`docs/demo.md`](docs/demo.md)). Remaining work is the native Rust/Tauri packaging (Keychain integration, code signing) and distribution.

Design notes in this repo:

- [`docs/architecture.md`](docs/architecture.md) — component layout
- [`docs/protocol.md`](docs/protocol.md) — the AUN Protocol
- [`docs/security.md`](docs/security.md) — security posture
- [`docs/clone-memory.md`](docs/clone-memory.md) — clones and memory

## Repository layout

- `apps/desktop/` — Tauri 2 + React + TypeScript desktop app
- `services/local-core/` — FastAPI Local Core (127.0.0.1 only, bearer auth required)
- `services/relay/` — forward-only relay server
- `packages/protocol/` — AUN Protocol message schemas (JSON Schema)
- `scripts/` — environment checks and dev helpers

> Note: internal package and bundle identifiers still use the project's former codename (`twinlink_core`, etc.). The public rename to ENISHI is in progress.

## Tech stack

TypeScript · React · Tauri 2 · Python · FastAPI · SQLite

## Setup

Requires macOS 13+, Node.js 20+, Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Rust (for the Tauri build).

```bash
npm install                                   # frontend deps
cd services/local-core && uv sync --group dev # Python deps
./scripts/check_macos_env.sh                  # verify toolchain
```

Run the desktop app (Tauri generates a random port + token for the Local Core and tears it down on exit):

```bash
./scripts/dev_desktop.sh
```

Run the Local Core on its own for API development:

```bash
./scripts/dev_core.sh   # http://127.0.0.1:8765
npm run dev             # Vite dev server (http://localhost:5173)
```

## Tests

```bash
# Python
cd services/local-core && uv run --group dev pytest
uv run --group dev ruff check . && uv run --group dev mypy twinlink_core

# TypeScript
npm run test && npm run typecheck

# Rust
cd apps/desktop/src-tauri && cargo test
```

---

Built by [Nakamura Masashi](https://github.com/Maaa2005). See also [Stellise](https://github.com/Maaa2005/Stellise), an on-device AI alarm app on the App Store.
