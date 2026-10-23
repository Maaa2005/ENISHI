# AUN Protocol 0.2

The AUN Protocol specification lives in
[`packages/protocol/SPEC.md`](../packages/protocol/SPEC.md). The machine-readable
contract is `packages/protocol/schemas/negotiation-message.schema.json`, and the
canonicalization vectors are `packages/protocol/test-vectors/jcs-v0.2.json`.
CI validates generated envelopes against the schema and the JCS vectors.

## Version migration

- New nodes advertise `aun/0.2` and `aun/0.1` in their agent card.
- Local Core can verify `aun/0.1` envelopes during the migration window.
- `aun/0.1` is deprecated and must not be used by new third-party
  implementations.
- Verification of `aun/0.1` is planned to be removed in the next breaking
  protocol release.
