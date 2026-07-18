# ENISHI two-node + relay demo

## Presentation demo (recommended)

Start a fresh two-person demo, seed the users/agents/peer trust automatically,
create a negotiation that is waiting for the presenter's approval, and launch
the browser UI:

```bash
./scripts/run_demo_presentation.sh
```

The launcher opens the correct demo URL automatically. If the browser does not
open, use the `Demo UI is ready` URL printed in the terminal. Do not reuse an
older `localhost:5173` tab because each presentation uses a new isolated port.
The launcher chooses
free loopback ports automatically, so an older rehearsal cannot block startup.
The generated data is isolated in a new
`.tmp/enishi-demo.*` directory on every run, so an earlier rehearsal cannot
pollute the presentation. Press Ctrl-C in the terminal to stop the UI, both
Local Cores, and the Relay.

The prepared story is:

1. Mizuno's agent asks Nakamura's agent for a 30-minute ENISHI progress meeting.
2. The agents compare availability without sending either raw calendar.
3. Nakamura's relationship policy stops the agent before it commits.
4. Approve it in **Approvals**. The UI updates the pending badge immediately
   and presents **View negotiation log** / **View agreement** as the next step.
5. Show the signed exchange in **Negotiations**, then the human-readable
   confirmed time and AUN Protocol record in **Agreements**.
6. Open **Memories** to explain that preferences, relationship rules, and
   privacy policy stay local. Open **Clones** to show the active personal
   agent's confidence, memory basis, delegation boundary, and approval gate.
7. Finish with **Audit log** to show the verifiable sequence from clone setup
   and peer trust through negotiation, human approval, and agreement. Point out
   that the screen receives allow-listed metadata only, never memory bodies,
   tokens, or key material.
8. If time remains, open **Projects** and **AI tasks**. The launcher registers
   this ENISHI checkout with restricted permissions and completes one harmless
   mock task, demonstrating how a clone receives only project-scoped context.

Before the browser opens, the launcher checks both Local Cores, local bearer
authentication, the pending approval, the restricted project, the completed AI
task, and the exact CORS origin. A failed check stops startup instead of opening
a partially working presentation.

The first run requires the repository dependencies to be installed. After that,
the presentation launcher uses the repository virtual environment directly and
does not ask `uv` to rebuild the project over the network.

If a rehearsal is interrupted, press Ctrl-C once and run the same command
again. Every run uses a new data directory, so approvals and agreements from a
previous run cannot make the presentation appear empty.

## Manual developer demo

To verify the real pairing boundary without opening the UI, run:

```bash
./scripts/run_pairing_e2e.sh
```

This starts a fresh Relay and two isolated Local Cores, exchanges signed
`enishi-card/2` cards, proves each card first creates only a `pending` peer,
checks the fingerprints, explicitly establishes trust, sends an agent request,
approves it, and confirms that both nodes persist the same agreement. All
processes and temporary ports are stopped automatically after the check.

Run three processes in three terminals:

```bash
./scripts/run_demo_relay.sh
./scripts/run_demo_user_a.sh
./scripts/run_demo_user_b.sh
```

Or start them all at once:

```bash
./scripts/run_demo_all.sh
```

| process | URL | token | data dir |
|---|---|---|---|
| Relay | `http://127.0.0.1:8870` | `relay-token-a` / `relay-token-b` | `.tmp/demo-relay` |
| User A | `http://127.0.0.1:8871` | `demo-token-a` | `.tmp/demo-user-a` |
| User B | `http://127.0.0.1:8872` | `demo-token-b` | `.tmp/demo-user-b` |

Each Local Core uses its own SQLite database, key, and data directory. The relay reads the real agent IDs from the current demo data directory and sets `RELAY_NODE_TOKENS` automatically.

## Pairing

The automated demo exchanges signed Agent Cards. For low-level API debugging,
read each node's public key:

```bash
curl -s -H "Authorization: Bearer demo-token-a" \
  http://127.0.0.1:8871/v1/node/identity

curl -s -H "Authorization: Bearer demo-token-b" \
  http://127.0.0.1:8872/v1/node/identity
```

Register B as a peer of A and A as a peer of B (fill in `agent_id` and `public_key` from the results above), then mark each trusted:

```bash
curl -s -X POST -H "Authorization: Bearer demo-token-a" -H "Content-Type: application/json" \
  -d '{"agent_id":"<B_AGENT_ID>","display_name":"Demo User B","public_key":"<B_PUBLIC_KEY>"}' \
  http://127.0.0.1:8871/v1/peers
curl -s -X POST -H "Authorization: Bearer demo-token-a" \
  http://127.0.0.1:8871/v1/peers/<B_AGENT_ID>/trust

curl -s -X POST -H "Authorization: Bearer demo-token-b" -H "Content-Type: application/json" \
  -d '{"agent_id":"<A_AGENT_ID>","display_name":"Demo User A","public_key":"<A_PUBLIC_KEY>"}' \
  http://127.0.0.1:8872/v1/peers
curl -s -X POST -H "Authorization: Bearer demo-token-b" \
  http://127.0.0.1:8872/v1/peers/<A_AGENT_ID>/trust
```

## Disclosure settings

Configure per-peer selective disclosure:

```bash
curl -s -X PUT -H "Authorization: Bearer demo-token-a" -H "Content-Type: application/json" \
  -d '{"allowed_memory_types":["schedule","preference"],"max_sensitivity":"internal","share_schedule":true,"share_skills":false,"extra":{}}' \
  http://127.0.0.1:8871/v1/peers/<B_AGENT_ID>/disclosure

curl -s -X PUT -H "Authorization: Bearer demo-token-b" -H "Content-Type: application/json" \
  -d '{"allowed_memory_types":["schedule","preference"],"max_sensitivity":"internal","share_schedule":true,"share_skills":false,"extra":{}}' \
  http://127.0.0.1:8872/v1/peers/<A_AGENT_ID>/disclosure
```

## Inspect it in the desktop UI

Point the desktop app at User A:

```bash
cd apps/desktop
VITE_CORE_PORT=8871 VITE_CORE_TOKEN=demo-token-a npm run dev
```

Walkthrough:

1. **Peers** — check peer status, fingerprints, and disclosure settings.
2. **Negotiation** — run `meeting.schedule` or `task.request` and watch the JSON messages on the timeline.
3. **Agreements** — inspect an agreement and move it to `fulfilled` or `cancelled`.
4. **Approvals** — approve or reject a `task.request` sitting in `waiting_approval`.
5. **Metrics** — run the comparison experiment against the email baseline: template, round trips, delta on/off, total tokens, message count, LLM call count, and reduction rate.

## Scheduling over the relay

On User A, create a user and an active clone:

```bash
curl -s -X POST -H "Authorization: Bearer demo-token-a" -H "Content-Type: application/json" \
  -d '{"display_name":"User A"}' http://127.0.0.1:8871/v1/users
curl -s -X POST -H "Authorization: Bearer demo-token-a" -H "Content-Type: application/json" \
  -d '{"purpose":"negotiation","provider_type":"mock"}' http://127.0.0.1:8871/v1/clones/<USER_A_ID>/ensure
curl -s -X POST -H "Authorization: Bearer demo-token-a" \
  http://127.0.0.1:8871/v1/clones/<CLONE_A_ID>/activate
```

Do the same for User B (a user plus an active clone).

Send `REQUEST` / `PROPOSE` from User A through the relay:

```bash
curl -s -X POST -H "Authorization: Bearer demo-token-a" -H "Content-Type: application/json" \
  -d '{"user_id":"<USER_A_ID>","peer_agent_id":"<B_AGENT_ID>","topic":"project planning","duration_minutes":30,"date_range":{"start":"2026-07-13","end":"2026-07-17"},"preferred_time_ranges":[{"start":"13:00","end":"18:00"}]}' \
  http://127.0.0.1:8871/v1/remote-negotiations
```

Process the inboxes on User B, then on User A if needed:

```bash
curl -s -X POST -H "Authorization: Bearer demo-token-b" \
  http://127.0.0.1:8872/v1/relay/inbox/process
curl -s -X POST -H "Authorization: Bearer demo-token-a" \
  http://127.0.0.1:8871/v1/relay/inbox/process
```

Check the agreement on both sides at `/v1/agreements`, the JSON timeline at `/v1/negotiations/{session_id}/messages`, and the token comparison in the **Metrics** view or `/v1/metrics/experiments`.
