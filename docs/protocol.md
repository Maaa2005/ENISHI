# TwinLink Protocol 0.1

The structured message format agents use to talk to each other.

Every message shares a common envelope and carries a typed `message_type`:
`REQUEST`, `PROPOSE`, `COUNTER`, `ACCEPT`, `REJECT`, `REQUEST_APPROVAL`,
`APPROVAL_RESULT`, `EXECUTE`, `RECEIPT`, `ERROR`. Proposals and counters are
exchanged as deltas rather than full state. The schemas are defined as JSON
Schema under `packages/protocol/schemas/`.
