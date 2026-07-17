# MCP control plane

`enishi-mcp` is a thin stdio MCP server for Codex and Claude Code. It does not read the SQLite database or run negotiation logic itself.

```text
Codex / Claude Code
        │ stdio
        ▼
services/enishi-mcp
        │ HTTP + MCP-scoped bearer token
        ▼
Local Core (127.0.0.1)
```

When Local Core starts, it writes `~/Library/Application Support/ENISHI/core.json` with mode `0600`. The file contains the loopback port, an MCP-only token, and the Core PID. It is removed when Core exits. The MCP server never starts Core by itself.

The MCP token is allowed to use only:

- `GET /v1/peers`
- `GET /v1/negotiations` and one negotiation's messages
- `GET /v1/agent/card`
- `POST /v1/agent/requests`
- `POST /v1/peers/from-card`

It cannot approve or reject, trust a peer, block a peer, edit disclosure settings, inspect memories, or execute coding tasks.

The exposed tools are `list_peers`, `list_negotiations`, `get_negotiation`, `get_my_card`, `create_request`, and `add_peer_from_card`. Peer-provided names, topics, payloads, and deltas are labeled `UNTRUSTED CONTENT` in tool results.

`get_my_card` returns an Ed25519-signed identity card. `add_peer_from_card` verifies the signature, Agent ID, and fingerprint, then creates only a `pending` peer. The user must compare the fingerprint and establish trust in the ENISHI UI.
