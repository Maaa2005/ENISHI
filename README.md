# ENISHI (縁) — Your AI Agent, Negotiating on Your Behalf

*A platform where your personal AI agent represents you — talking to other people's agents to negotiate, coordinate, and settle the everyday back-and-forth so you don't have to. macOS desktop app.*

## The idea

You have a personal AI agent — a "clone" that knows your preferences, your calendar, and your constraints. When you need to arrange something with another person, you don't do the back-and-forth yourself: your clone talks to their clone.

The two agents work out the details between them — a meeting time, the terms of a deal, who does what by when — and each comes back to its owner with a proposal. Nothing is final until the human approves it.

Booking a meeting across two calendars is the first thing ENISHI does today. But the goal is much bigger: any coordination between two people that currently takes a dozen messages — business arrangements, negotiations, plans, favors — carried out by agents that represent each side faithfully, keep private things private, and never act on their own.

Where this goes: once everyone has an agent that can speak for them, coordination stops being something you do by hand. You don't trade twenty messages to find a time, haggle over a delivery window, or chase three people for a sign-off — your agent and theirs settle it and hand each side the result to approve. The same rails work whether the other party is a friend, a client, or a company's agent. What ENISHI is really building is the protocol and the trust model that make that exchange safe: an agent that can prove who it speaks for, reveal only what it must, and never commit you to anything you didn't agree to. That's the connection — the 縁 — I want to make routine.

ENISHI is a macOS desktop app I'm building as a personal project. It's early, and this repo is the working codebase; the detailed internal design spec is kept private.

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
               durable mailbox,
               destination authz,
               size/rate limits,
               minimal logging)
```

Codex and Claude Code can also use ENISHI as the primary control surface:

```text
Codex / Claude Code ──stdio──► enishi-mcp ──HTTP + scoped token──► Local Core
```

The real work happens in the **Local Core**, a FastAPI service that binds to `127.0.0.1` only. Tauri launches it as a child process with a random port and a random UI bearer token per session. Local Core also writes a private `core.json` discovery file for `enishi-mcp`, using a separate restricted token. MCP may observe negotiations and create requests, but cannot approve actions, trust peers, or change disclosure policy. The desktop UI remains the human approval and audit surface.

## The AUN Protocol

Agents exchange structured messages, not free text. Each message has a typed `message_type`:

`REQUEST` → `PROPOSE` → `COUNTER` → `ACCEPT` / `REJECT` → `REQUEST_APPROVAL` → `APPROVAL_RESULT` → `EXECUTE` → `RECEIPT`, plus `ERROR`.

A negotiation is a state machine over these messages. Proposals and counter-proposals are exchanged as deltas rather than full state, so a round of haggling stays small. The schemas live in `packages/protocol/` as JSON Schema, shared between both sides.

## Delegation, selective disclosure, and the human gate

Three ideas do the heavy lifting:

- **Clone agents.** When you delegate a task, ENISHI spins up a scoped agent (a "clone"). It starts in `review_required` state and cannot perform any high-privilege action until you explicitly activate it. The default profile denies destructive operations outright.
- **Selective disclosure.** You configure, per peer, what your agent is allowed to reveal. A negotiating agent answers "does this slot work?" without ever transmitting the underlying calendar. Memories marked `secret` never leave the device and are never packed into a clone's context.
- **Risk-based approval gate with expiry.** Explicitly delegated low-risk negotiations may complete automatically. Destructive, externally visible, low-confidence, or policy-restricted actions stop for human approval. Approvals carry an `expires_at`; once expired, the action can no longer run, so a stale "yes" from last week can't be replayed into an action today.
- **Explainable personal context.** The desktop app shows which local memories, relationship rules, and delegation boundaries shaped the active clone, while hiding secret memory content and keeping raw personal data off the wire.
- **Privacy-safe audit trail.** Trust changes, signed negotiation steps, human decisions, rejected envelopes, and agreements appear in a local timeline. The UI API exposes only allow-listed metadata; memory bodies, tokens, and key material are excluded.

## Security design

The threat model assumes the relay is untrusted and the other agent may be adversarial. Some of the concrete decisions:

- Local Core listens on `127.0.0.1` only — binding to `0.0.0.0` is explicitly disallowed.
- Bearer token comparison uses constant-time comparison (`secrets.compare_digest`) to avoid timing leaks.
- The app never builds shell command strings. External CLIs are invoked as a command name plus a validated argument array, never a concatenated string.
- CLI detection is limited to `shutil.which` plus a `--version` probe. ENISHI never reads another tool's credentials.
- ENISHI does not store external-provider credentials. Tauri-launched Local Core stores the node signing key in the macOS Keychain; standalone CLI demos use a local `0600` fallback file.

More detail is in [`docs/security.md`](docs/security.md).

## Status

The presentation build is complete and demoable across two local nodes plus a relay. It includes the negotiation loop, node identity, selective disclosure, clone lifecycle, project-scoped AI tasks, the human-approval gate, agreements, and a privacy-safe audit trail. A fresh isolated presentation scenario starts with one command (see [`docs/demo.md`](docs/demo.md)). Production packaging now embeds Local Core as a self-contained macOS sidecar and includes the final ENISHI app icon, so the `.app` does not depend on a repository checkout, Python, or `uv` on the user's machine. The Relay now has a SQLite-backed mailbox, preserving unacknowledged deliveries, TTL expiry, and rate-limit state across restarts. Remaining distribution work is code signing, notarization, update delivery, and deployment-grade Relay authentication, TLS, monitoring, and operations.

The real two-node pairing boundary is also executable as a self-check: `./scripts/run_pairing_e2e.sh` exchanges signed Agent Cards, proves that registration stops at `pending`, requires explicit fingerprint trust, sends a request through the Relay, waits for human approval, and confirms that both nodes persist the same canonical agreement.

Codex and Claude Code can use ENISHI without opening the desktop app. The MCP control plane starts a loopback-only headless Local Core on demand, while the separate memory MCP reads and writes the second brain. Human approval, fingerprint trust, and disclosure changes remain in the desktop UI; opening it securely hands the same database from the headless Core to a UI-owned Core without publishing the UI token.

Design notes in this repo:

- [`docs/architecture.md`](docs/architecture.md) — component layout
- [`docs/protocol.md`](docs/protocol.md) — the AUN Protocol
- [`docs/security.md`](docs/security.md) — security posture
- [`docs/clone-memory.md`](docs/clone-memory.md) — clones and memory
- [`docs/mcp-control-plane.md`](docs/mcp-control-plane.md) — Codex / Claude Code control plane

## Repository layout

- `apps/desktop/` — Tauri 2 + React + TypeScript desktop app
- `services/local-core/` — FastAPI Local Core (127.0.0.1 only, bearer auth required)
- `services/enishi-mcp/` — thin stdio MCP-to-Local-Core control plane
- `services/relay/` — forward-only relay server with a persistent SQLite mailbox
- `packages/protocol/` — AUN Protocol message schemas (JSON Schema)
- `scripts/` — environment checks and dev helpers

## Tech stack

TypeScript · React · Tauri 2 · Python · FastAPI · SQLite

## Setup

Requires macOS 13+, Node.js 20+, Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Rust (for the Tauri build).

```bash
npm install                                   # frontend deps
cd services/local-core && uv sync --group dev # Python deps
./scripts/check_macos_env.sh                  # verify toolchain
```

Run the desktop app (Tauri generates a random port + token and safely takes over from an MCP-started headless Core when needed):

```bash
./scripts/dev_desktop.sh
```

Register ENISHI for Codex and Claude Code:

```bash
./scripts/install-agent-integrations.sh
```

Build an unsigned `.app` and DMG for the current Mac architecture:

```bash
npm run bundle:macos
```

The build creates a self-contained Local Core sidecar with PyInstaller, then verifies the app identifier, minimum macOS version, bundled Desktop/Core executables, DMG, and checksum. It uses Tauri's CI-safe DMG mode so packaging does not depend on scripting Finder. Signing and notarization are intentionally separate because they require Apple Developer credentials.

Run the Local Core on its own for API development:

```bash
./scripts/dev_core.sh   # http://127.0.0.1:8765
npm run dev             # Vite dev server (http://localhost:5173)
```

## Tests

```bash
# Python
uv run --group dev pytest services/local-core/tests services/enishi-mcp/tests
uv run --group dev ruff check services/local-core/enishi_core services/enishi-mcp
uv run --group dev mypy services/local-core/enishi_core services/enishi-mcp/enishi_mcp

# TypeScript
npm run test && npm run typecheck

# Rust
cd apps/desktop/src-tauri && cargo test
```

---

Built by [Nakamura Masashi](https://github.com/Maaa2005). See also [Stellise](https://github.com/Maaa2005/Stellise), an on-device AI alarm app on the App Store.
