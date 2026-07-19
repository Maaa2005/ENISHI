from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEPLOYMENT_DIR = REPOSITORY_ROOT / "deploy" / "relay"


def test_relay_is_internal_and_production_defaults_fail_closed() -> None:
    compose = (DEPLOYMENT_DIR / "compose.yaml").read_text()
    relay_service = compose.split("\n  caddy:", 1)[0]

    assert "expose:" in relay_service
    assert "ports:" not in relay_service
    assert 'RELAY_REQUIRE_HASHED_TOKENS: "true"' in relay_service
    assert 'RELAY_DOCS_ENABLED: "false"' in relay_service
    assert "cap_drop:" in relay_service
    assert "read_only: true" in relay_service


def test_caddy_terminates_tls_and_blocks_public_metrics() -> None:
    compose = (DEPLOYMENT_DIR / "compose.yaml").read_text()
    caddyfile = (DEPLOYMENT_DIR / "Caddyfile").read_text()

    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert "respond @metrics 404" in caddyfile
    assert "reverse_proxy relay:8080" in caddyfile
    assert "health_uri /ready" in caddyfile
    assert "Strict-Transport-Security" in caddyfile


def test_relay_container_runs_unprivileged_with_readiness_healthcheck() -> None:
    dockerfile = (DEPLOYMENT_DIR / "Dockerfile").read_text()

    assert "USER 10001:10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "http://127.0.0.1:8080/ready" in dockerfile
    assert '"--no-server-header"' in dockerfile
    assert "uv export --quiet --locked --package enishi-relay" in dockerfile
    assert "pip install --no-cache-dir --require-hashes" in dockerfile


def test_prometheus_alerts_cover_core_failure_modes() -> None:
    alerts = (DEPLOYMENT_DIR / "prometheus-alerts.yml").read_text()

    assert "EnishiRelayDown" in alerts
    assert "enishi_relay_readiness_failures_total" in alerts
    assert "enishi_relay_pending_messages" in alerts
    assert 'code="RELAY_UNAUTHORIZED"' in alerts
    assert "resets(enishi_relay_uptime_seconds" in alerts
