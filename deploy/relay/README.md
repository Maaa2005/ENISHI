# Relay production deployment

This deployment keeps the Relay on an internal Docker network and exposes only
Caddy. Caddy obtains and renews the TLS certificate automatically. The public
proxy returns `404` for `/metrics`; a monitoring agent must scrape the Relay
directly from `relay-backend`.

## Provision

1. Point the Relay domain's DNS record at the host and allow inbound TCP 80/443
   and UDP 443. Do not publish port 8080.
2. Generate one high-entropy token per node:

   ```bash
   uv run --project services/relay python -m relay.token_tool --generate
   ```

3. Copy `.env.example` to a private `.env`, replace the example domain, email,
   and token digests, then start the stack:

   ```bash
   docker compose --env-file deploy/relay/.env \
     -f deploy/relay/compose.yaml up -d --build
   ```

4. Verify both probes over TLS:

   ```bash
   curl --fail https://relay.example.com/health
   curl --fail https://relay.example.com/ready
   ```

`/health` proves that the process is alive. `/ready` additionally opens a
SQLite write transaction and reads the mailbox table; load balancers should
route traffic only when it returns `200`. The container healthcheck uses
`/ready`.

## Monitoring

`GET /metrics` returns Prometheus text with uptime, pending delivery count,
accepted/fetched/acknowledged totals, readiness failures, and rejection totals.
It has no node IDs, message IDs, bearer tokens, token hashes, or envelope data.
Scrape `http://relay:8080/metrics` only from a monitoring container attached to
the internal `relay-backend` network.

At minimum, alert on repeated readiness failures, a continuously growing
pending-message gauge, authentication rejection spikes, and restart loops.
Back up the `relay-data` volume and test restoration before public operation.
