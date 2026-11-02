> **Historical document.** This describes `aun/0.2` as implemented by the frozen ENISHI app (development stopped 2026-10-23). The nine-type flow listed below is the original design, not the implemented behaviour. The current protocol is maintained at https://github.com/Maaa2005/aun-protocol (`aun/0.3`); refer to it for new work.

# AUN Protocol 0.2

The structured message format ENISHI agents use to talk to each other.

Every message shares a common envelope and carries a typed `message_type`:
`REQUEST`, `PROPOSE`, `COUNTER`, `ACCEPT`, `REJECT`, `REQUEST_APPROVAL`,
`APPROVAL_RESULT`, `EXECUTE`, `RECEIPT`, `ERROR`. Proposals and counters are
exchanged as deltas rather than full state.

As implemented, only `REQUEST`, `PROPOSE`, `COUNTER` (at most 3 rounds), `ACCEPT`,
`REJECT` and `ERROR` are sent between nodes. `REQUEST_APPROVAL`,
`APPROVAL_RESULT`, `EXECUTE` and `RECEIPT` are never sent and are rejected on
receive (`services/local-core/enishi_core/services/protocol_state.py`); human
approval is a local step before `ACCEPT`. Messages are signed, not encrypted. The schemas are defined as JSON
Schema under `packages/protocol/schemas/`.

## Signed representation

AUN 0.2 requires both `sender_node_id` and `receiver_node_id`. Personal agent
IDs describe who is represented; node IDs bind transport and signatures to the
specific devices carrying the exchange.

The signature covers every envelope field except `signature`. The payload hash
covers `{ "payload": ..., "delta": ... }`. Both byte strings use the JSON
Canonicalization Scheme from RFC 8785. Implementations must reject values that
JCS cannot represent, including `NaN`, positive or negative infinity, and
integers outside the interoperable IEEE-754 domain.

Cross-language implementations must pass the vectors in
`packages/protocol/test-vectors/jcs-v0.2.json` before exchanging signed
messages.

## Version migration

- New ENISHI nodes advertise `aun/0.2` and `aun/0.1`, preferring 0.2.
- New Relay exchanges use 0.2 and require sender and receiver node IDs.
- Local Core can verify existing 0.1 envelopes during the migration window,
  using the legacy Python-compatible canonical form.
- 0.1 is deprecated and must not be used for new third-party implementations.
- Removal of 0.1 verification is planned for the next breaking protocol release
  after deployed peers have migrated.

The 0.2 JSON Schema is the public wire contract. CI validates generated
envelopes against it and checks the JCS golden vectors to prevent the Python
validator and schema from drifting silently.
