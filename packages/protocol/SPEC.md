# AUN Protocol 0.2 Specification

AUN is the wire protocol ENISHI agents use to negotiate with each other. This
document describes the message format, the message flow, and the checks a
receiver performs, so that a third party can implement a compatible node.

This document describes the behavior of the reference implementation (ENISHI
Local Core). Where it says a receiver rejects something, the reference
implementation rejects it. The machine-readable contract is
[schemas/negotiation-message.schema.json](schemas/negotiation-message.schema.json)
(JSON Schema 2020-12). The canonicalization vectors are in
[test-vectors/jcs-v0.2.json](test-vectors/jcs-v0.2.json).

## 1. Model

- A **node** is one device. It has an Ed25519 key pair. Its **node ID** is
  `agt_` followed by the first 16 lowercase hex characters of the SHA-256 of the
  raw 32-byte public key.
- A **personal agent** is the party a node represents. Personal agent IDs say who
  is represented. Node IDs bind transport and signatures to the device carrying
  the exchange.
- A **session** is one negotiation between two personal agents about one
  `intent`. All messages of a session share `session_id`.
- A message is one signed JSON object, the **envelope**.

## 2. Envelope

All fields are required. No other fields are allowed (`additionalProperties:
false`).

| Field | Type | Meaning |
| --- | --- | --- |
| `protocol` | string | Always `"aun/0.2"`. |
| `message_id` | string, non-empty | Unique per message. Used for replay detection. The reference sender uses a random UUID in hex. |
| `session_id` | string, non-empty | Identifies the session. Chosen by the initiator in its first message. |
| `sender_agent_id` | string, non-empty | Personal agent ID of the sender. |
| `receiver_agent_id` | string, non-empty | Personal agent ID of the receiver. |
| `sender_node_id` | string, non-empty | Node ID of the sending device. Its public key verifies `signature`. |
| `receiver_node_id` | string, non-empty | Node ID of the receiving device. |
| `message_type` | string | One of the types in section 3. |
| `intent` | string, non-empty | What is being negotiated (section 5). Fixed for the whole session. |
| `session_version` | integer, 1 or more | Version of the session terms. The reference implementation uses `1`. Must stay equal to the value recorded at session start. |
| `sequence` | integer, 1 or more | Position in the session. Counts messages of both parties on one shared counter. Starts at 1 and increases by exactly 1 per message. |
| `payload` | object | Public context. Carries the request details in `REQUEST` and `public_reason` in some replies. `{}` otherwise. |
| `delta` | object | The change being proposed, answered or accepted. Not full state. |
| `requires_human_approval` | boolean | The reference sender always sets `false`. A receiver stores the value but does not act on it. |
| `nonce` | string, non-empty | Random value included in the signature. The reference sender uses 16 random bytes in hex. |
| `created_at` | date-time string | Time the sender created the message. The reference receiver requires a timezone offset. |
| `payload_hash` | string | Lowercase hex SHA-256 digest, 64 characters (section 7). |
| `signature` | string, non-empty | Base64 of the 64-byte Ed25519 signature (section 7). |

`payload.public_reason`, when present, must be one of `no_common_slot`,
`constraint_violation`, `policy_declined` (section 9). Other `payload` keys are
allowed by the schema; their meaning depends on the intent.

The schema does not set length limits on strings.

Illustrative envelope (values shortened; `<...>` stands for a computed value):

```json
{
  "protocol": "aun/0.2",
  "message_id": "<uuid-hex>",
  "session_id": "<session-id>",
  "sender_agent_id": "<personal-agent-id-A>",
  "receiver_agent_id": "<personal-agent-id-B>",
  "sender_node_id": "agt_<16-hex>",
  "receiver_node_id": "agt_<16-hex>",
  "message_type": "PROPOSE",
  "intent": "meeting.schedule",
  "session_version": 1,
  "sequence": 2,
  "payload": {},
  "delta": {"candidate_slots": [{"start": "2099-01-01T00:00+09:00", "end": "2099-01-01T00:30+09:00"}]},
  "requires_human_approval": false,
  "nonce": "<hex>",
  "created_at": "<ISO 8601 date-time with offset>",
  "payload_hash": "<64 lowercase hex>",
  "signature": "<base64>"
}
```

## 3. Message types

The schema defines ten values. Six are used on the wire today.

| Type | Sent by | When | `payload` | `delta` |
| --- | --- | --- | --- | --- |
| `REQUEST` | Initiator | Opens the session. Always `sequence` 1. | The request details (section 5). | `{}` |
| `PROPOSE` | Initiator | Immediately after `REQUEST`, as `sequence` 2. | `{}` | The initiator's first offer. |
| `COUNTER` | Either party | Answers an offer with a different offer. | `{"public_reason": ...}` | The new offer. |
| `ACCEPT` | Either party | Agrees to the standing offer. Ends the session as agreed. | `{}` | The agreed value. |
| `REJECT` | Either party | Declines. Ends the session as failed. | `{"public_reason": ...}` | `{"code": ...}` |
| `ERROR` | Either party | Ends the session as failed when negotiation cannot continue. | `{}` | `{"code": ...}` |

`REQUEST_APPROVAL`, `APPROVAL_RESULT`, `EXECUTE` and `RECEIPT` are defined in
the schema. The current implementation does not send them, and a receiver
rejects them with `INVALID_STATE_TRANSITION` (section 8). Human approval is a
local step, not a wire message (section 6).

Offers are exchanged as deltas, not as full state. The offer shape depends on the
intent (section 5).

## 4. Session state

A receiver tracks, per session: the last `sequence`, the type of the last
negotiation message, the number of `COUNTER` messages so far, the peer node, the
parties, `intent`, `session_version`, and a status.

Allowed transitions, by the type of the previous message:

| Previous | Next may be |
| --- | --- |
| (none) | `REQUEST` |
| `REQUEST` | `PROPOSE`, `REJECT`, `ERROR` |
| `PROPOSE` | `ACCEPT`, `COUNTER`, `REJECT`, `ERROR` |
| `COUNTER` | `ACCEPT`, `COUNTER`, `REJECT`, `ERROR` |

Further rules:

- After `ACCEPT`, `REJECT` or `ERROR` the session is terminal. Any later message
  is rejected.
- `sequence` must equal the last recorded `sequence` plus 1. The first message is
  `REQUEST` with `sequence` 1.
- A `COUNTER` is rejected when the session already holds 3 `COUNTER` messages
  (counted over both parties). At most 3 `COUNTER` messages are accepted.
- While a receiver waits for its own human decision (section 6), it accepts only
  `REJECT` or `ERROR` from the peer.

Separately from this cap, the reference implementation stops answering with
`COUNTER` earlier. When the session already holds 2 or more `COUNTER` messages
(including the one just received), its automatic reply is not a `COUNTER`.
What it sends instead depends on the intent (section 5).

## 5. Intents

An `intent` selects the negotiation domain. A node advertises the intents it can
receive in its agent card (section 10).

| Intent | Remote | Notes |
| --- | --- | --- |
| `meeting.schedule` | Yes | Find a common time slot. |
| `cost.split` | Yes | Agree on one party's share of a cost. |
| `task.request` | No | Local only. A node does not advertise it, and a `REQUEST` carrying it is rejected with `INTENT_NOT_SUPPORTED_FOR_REMOTE_REQUEST`. |

A `REQUEST` with an unregistered intent is rejected with `UNKNOWN_INTENT`.

### 5.1 `meeting.schedule`

`REQUEST` payload:

```json
{
  "intent": "meeting.schedule",
  "topic": "...",
  "duration_minutes": 30,
  "date_range": {"start": "2026-08-03", "end": "2026-08-03"},
  "preferred_time_ranges": [{"start": "13:00", "end": "15:00"}],
  "timezone": "Asia/Tokyo"
}
```

- `topic`: 1 to 500 characters. `duration_minutes`: integer from 1 to 480.
- `date_range`: dates as `YYYY-MM-DD`.
- `preferred_time_ranges`: at least one `{"start","end"}` in `HH:MM`, start before
  end.
- `timezone`: the initiator's timezone.

A **slot** is `{"start": ..., "end": ...}` with ISO 8601 date-times that carry a
UTC offset, at minute precision, for example
`{"start":"2099-01-01T00:00+09:00","end":"2099-01-01T00:30+09:00"}`. Two slots
are the same when their start and end are the same instants, even if their
offsets differ.

Deltas:

- `PROPOSE` and `COUNTER`: `{"candidate_slots": [slot, ...]}`. The reference
  sender offers at most 5 slots per message. It generates candidates in
  30-minute steps, at most 20, from the date range and preferred time ranges,
  and leaves out times it is busy.
- `ACCEPT`: `{"selected_slot": slot}`.

Reply rule: the replier intersects the received candidates with its own. If a
common slot exists and its local policy allows an automatic answer, it sends
`ACCEPT` with the first common slot. If there is no common slot, it sends
`COUNTER` with its own candidates and `public_reason` `no_common_slot`. If its
policy requires a human decision, see section 6.

If the exchange reaches the automatic round limit without agreement, the replier
sends `ERROR` with `delta` `{"code": "NO_AVAILABLE_SLOT"}`.

### 5.2 `cost.split`

`REQUEST` payload:

```json
{
  "intent": "cost.split",
  "title": "...",
  "total_amount": 10000.0,
  "currency": "JPY",
  "proposed_share": 3000.0,
  "deadline": null
}
```

- `title`: 1 to 500 characters. `total_amount`: number greater than 0.
- `currency`: 3 characters. The reference implementation uses `JPY` when none is
  given.
- `proposed_share`: number from 0 up to `total_amount`. This is the share
  proposed for the responder.
- `deadline`: `YYYY-MM-DD` or `null`.

Deltas:

- `PROPOSE` and `COUNTER`: `{"proposed_share": number}`. A `COUNTER` amount is
  rounded to 2 decimals.
- `ACCEPT`: `{"agreed_share": number}`.
- `REJECT`: `{"code": "COST_SHARE_EXCEEDS_LIMIT"}` when the offer is beyond what
  the replier will ever accept.

Reply rule: the replier either accepts the standing offer, counters with a
different amount, asks its human (section 6), or rejects. An automatic
`COUNTER` carries `public_reason` `constraint_violation`. When the replier would
counter and the session already holds 2 `COUNTER` messages, it does not send
`COUNTER` or `ERROR`. It asks its human instead (section 6).

## 6. Message sequences

Roles: the **initiator** starts the session. The **responder** receives it.
After `PROPOSE`, the two parties alternate replies.

Meeting with a common slot:

```
Initiator                          Responder
  REQUEST   (seq 1)  ---------->   validate, record session, no reply
  PROPOSE   (seq 2)  ---------->   intersect candidates
                     <----------   ACCEPT (seq 3)   selected_slot
```

Meeting with no common slot (the shape the golden tests check):

```
  REQUEST (1), PROPOSE (2)  ---->
                     <----------   COUNTER (3)  public_reason: no_common_slot
  COUNTER (4)        ---------->
                     <----------   ERROR (5)    code: NO_AVAILABLE_SLOT
```

`cost.split` follows the same shape with `proposed_share` offers. The exchange
ends with `ACCEPT` (`agreed_share`), `REJECT`, or a human decision.

The replier's local policy decides whether a reply is automatic. When the
decision needs a human (for example, delegation is off, confidence is low,
auto-accept is disabled, or the relationship requires approval):

1. The replier sends nothing to the peer. The session waits for its human.
   Meanwhile it accepts only `REJECT` or `ERROR` from the peer.
2. The human approves, rejects, or lets the request expire.
3. Approve: the replier sends `ACCEPT` or `COUNTER`. For `meeting.schedule`,
   the approval lists a selected slot, if any, and candidate slots. With no
   override, the reply is `ACCEPT` with `selected_slot` if a slot was selected,
   and otherwise `COUNTER` with up to 5 of the listed candidates. The human may
   instead pick one of the listed candidates: `ACCEPT` if it is the selected
   slot, `COUNTER` with that single slot if not. A pick that is not listed is
   refused locally. A `COUNTER` sent this way carries `public_reason`, derived
   from the internal reason of the approval. For `cost.split`, the human may override the amount and the reply is
   `ACCEPT` with `agreed_share`. After a `COUNTER`, the session stays open.
4. Reject or expiry: the replier sends `REJECT` with `payload`
   `{"public_reason": "policy_declined"}` and `delta` `{"code": "HUMAN_REJECTED"}`
   or `{"code": "APPROVAL_EXPIRED"}`.

The approval step can happen on either side, including the initiator when it
receives a `COUNTER`.

## 7. Signing

The signature covers every envelope field except `signature`, including
`payload_hash`.

1. Compute `payload_hash` as the lowercase hex SHA-256 of the UTF-8 bytes of the
   JCS (RFC 8785) serialization of `{"payload": <payload>, "delta": <delta>}`.
2. Build the envelope with `payload_hash` set and without `signature`.
3. Serialize the envelope with JCS (RFC 8785). Sign those bytes with the sender
   node's Ed25519 private key.
4. Set `signature` to the standard Base64 (with padding) of the signature.

A receiver verifies with the public key it holds for `sender_node_id`. It never
takes the key from the message.

Notes:

- JCS sorts keys, uses no insignificant whitespace, and serializes numbers as
  ECMAScript does. For example `3000.0` is serialized as `3000`.
- Reject values JCS cannot represent: `NaN`, infinities, and integers outside
  the range -(2^53 - 1) to 2^53 - 1.
- An implementation must reproduce the vectors in
  [test-vectors/jcs-v0.2.json](test-vectors/jcs-v0.2.json) before exchanging
  signed messages.

## 8. Receiver checks

For each incoming envelope, in this order, the reference implementation does the
following. A failed check drops the message. It sends no reply to the sender.

1. **Known peer.** The peer for `sender_node_id` must exist and be marked
   trusted. Else `PEER_NOT_TRUSTED`.
2. **Identity mapping.** The trusted peer's personal agent ID must equal
   `sender_agent_id`. `receiver_node_id` must be this node. `receiver_agent_id`
   must be a personal agent of this node. Else `AGENT_IDENTITY_MISMATCH`.
3. **Schema.** The envelope must match the 0.2 schema, and `created_at` must
   parse as a date-time with a timezone. Else `MESSAGE_SCHEMA_INVALID`.
4. **Signature and hash.** The signature must verify, and `payload_hash` must
   match. Else `MESSAGE_SIGNATURE_INVALID`.
5. **Time window.** `created_at` must be within 300 seconds of the receiver's
   clock, in the past or the future. Else `MESSAGE_EXPIRED`.
6. **Replay.** `message_id` is recorded for 3600 seconds. A second message with
   the same `message_id` is dropped without processing (`MESSAGE_REPLAYED`).
   Only `message_id` is tracked. `nonce` is covered by the signature but is not
   checked separately.
7. **State machine.** Section 4. Else `INVALID_STATE_TRANSITION`. This includes a
   message for an unknown session that is not a `REQUEST`, and the four unused
   message types.
8. **For a `REQUEST`:** the `intent` must be registered and remote-capable
   (`UNKNOWN_INTENT`, `INTENT_NOT_SUPPORTED_FOR_REMOTE_REQUEST`). The payload
   must be valid for the intent (`INVALID_NEGOTIATION_PAYLOAD`). If the peer's
   agent card lists capabilities, they must include this intent and
   `aun/0.2` (`PEER_CAPABILITY_MISMATCH`). A peer whose card has no
   capabilities is accepted.
9. **For any other message (session binding).** The message must belong to the
   session it names. `sender_node_id` must equal the node that sent the
   `REQUEST`. `sender_agent_id` and `receiver_agent_id` must be the two parties
   of the session and must differ. `intent` and `session_version` must equal the
   values recorded at session start. Else `SESSION_BINDING_MISMATCH`. Without
   this check, any trusted peer that knows a `session_id` and the next `sequence`
   could inject an `ACCEPT` into someone else's session.

The codes in this section are receiver-side outcomes. They are never carried in
an envelope.

## 9. Errors on the wire

`REJECT` and `ERROR` carry a code in `delta.code`. The codes the reference
implementation sends:

| Message | `delta.code` | Meaning |
| --- | --- | --- |
| `ERROR` | `NO_AVAILABLE_SLOT` | `meeting.schedule` ended without a common slot. |
| `ERROR` | `NEGOTIATION_ROUNDS_EXHAUSTED` | Default for a domain that sets no code of its own, when the automatic round limit is reached. |
| `REJECT` | `HUMAN_REJECTED` | The human declined. |
| `REJECT` | `APPROVAL_EXPIRED` | The human did not decide in time. |
| `REJECT` | `COST_SHARE_EXCEEDS_LIMIT` | `cost.split`: the offered share is beyond the replier's limit. |

A receiver treats `delta.code` as an opaque string. On `REJECT` or `ERROR` it
ends the session as failed and stores the code, or the message type name if
there is none, and `payload.public_reason` if present.

### Minimal disclosure and public reasons

A message must carry only what the peer needs to continue. Never put the
following in `payload` or `delta`:

- Reservation values, limits and preference parameters. The reference tests scan
  every `cost.split` message for the keys `reservation_ratio`, `preferred_ratio`,
  `concession_ratio`, `max_auto_accept_amount` and `max_negotiable_amount`.
- Calendar content: titles and bodies of busy entries, and why a time was
  excluded. Only candidate slots are sent.
- Internal decision reason codes.

The reason for a `COUNTER` or `REJECT` is sent as one of three coarse categories
in `payload.public_reason`:

| Value | Used when |
| --- | --- |
| `no_common_slot` | The two candidate sets do not intersect. |
| `constraint_violation` | The offer is outside what the replier will accept (preferences, limits, concession step). The constraint is not disclosed. |
| `policy_declined` | The replier's delegation or approval policy, or its human, declined. Also the default. |

## 10. Agent card and capabilities

Before two nodes can talk, each holds the other's **agent card**. The exchange
of cards is not part of the message flow. The card gives a node what it needs to
verify messages and choose intents.

Card version `enishi-card/2`:

| Field | Meaning |
| --- | --- |
| `version` | `"enishi-card/2"`. Version `enishi-card/1` has no `capabilities`. |
| `agent_id` | The node ID. Must equal `agt_` plus the first 16 hex of the SHA-256 of the public key. |
| `personal_agent_id` | The personal agent represented. |
| `public_key` | Base64 of the raw 32-byte Ed25519 public key. |
| `fingerprint` | First 8 bytes of the SHA-256 of the public key, as colon-separated hex pairs. |
| `profile.display_name` | Name shown to humans. Must not be blank. |
| `capabilities` | See below. |
| `relay_endpoint` | Where the node receives messages. |
| `issued_at` | Issue time. |
| `signature` | Base64 Ed25519 signature by the node key. |

`capabilities`:

```json
{
  "timezone": "<IANA timezone name>",
  "supported_intents": ["meeting.schedule", "cost.split"],
  "protocol_versions": ["aun/0.2", "aun/0.1"]
}
```

`supported_intents` lists only intents the node can receive remotely.
`task.request` is not listed. A node must not send a `REQUEST` for an intent the
peer's card does not list, or to a peer whose card does not list `aun/0.2`
(`PEER_CAPABILITY_MISMATCH`). If the peer has no capabilities (an
`enishi-card/1` card), the reference sender sends only `meeting.schedule`.

The card signature is computed over the card without `signature`, serialized as
UTF-8 JSON with sorted keys, no whitespace, and non-ASCII characters left
unescaped. This is not JCS.

## 11. Transport

This section is informative.

- Messages travel through a relay that stores and forwards them. A message is
  addressed to the receiver's node ID.
- The relay accepts a message only when `sender_node_id` is the authenticated
  node. (For legacy `aun/0.1` envelopes without node IDs, it compares
  `sender_agent_id`.)
- The relay limits message size and request rate.

The relay does not verify the envelope signature. A receiver must run the
checks in section 8.

## 12. Versioning

- This document specifies `aun/0.2`. The `protocol` field of every message that
  conforms to this document is `"aun/0.2"`.
- `aun/0.1` is deprecated. It has no required node IDs and signs a Python-style
  canonical JSON (sorted keys, compact separators, non-ASCII unescaped) instead
  of JCS. Local Core can still verify existing 0.1 envelopes during migration.
  New third-party implementations must not use it.
- Removal of 0.1 verification is planned for the next breaking protocol release.
- A node lists the versions it supports in `capabilities.protocol_versions`.
