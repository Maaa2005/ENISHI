import hashlib
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# conftest.py と同じ値（tests パッケージ名が local-core 側と衝突するため直接定義）
AGENT_A = "agt_aaaa"
AGENT_B = "agt_bbbb"

SECRET_MARKER = "極秘予定の本文"


def _envelope(sender: str = AGENT_A, receiver: str = AGENT_B) -> dict[str, object]:
    return {
        "protocol": "aun/0.1",
        "message_id": "m001",
        "session_id": "s001",
        "sender_agent_id": sender,
        "receiver_agent_id": receiver,
        "message_type": "PROPOSE",
        "intent": "meeting.schedule",
        "session_version": 1,
        "sequence": 2,
        "payload": {},
        "delta": {"note": SECRET_MARKER},
        "requires_human_approval": False,
        "nonce": "abc",
        "created_at": "2026-07-11T12:00:00+00:00",
        "payload_hash": "x",
        "signature": "sig",
    }


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/v1/messages").status_code == 401
    assert client.post("/v1/messages", json=_envelope()).status_code == 401
    bad = client.get("/v1/messages", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "RELAY_UNAUTHORIZED"


def test_hashed_tokens_authenticate_and_rotate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from relay.config import get_relay_settings
    from relay.main import create_app

    old_token = "old-token-for-a"
    new_token = "new-token-for-a"
    token_b = "token-for-b"
    hashes = ",".join(
        [
            f"{AGENT_A}={hashlib.sha256(old_token.encode()).hexdigest()}",
            f"{AGENT_A}={hashlib.sha256(new_token.encode()).hexdigest()}",
            f"{AGENT_B}={hashlib.sha256(token_b.encode()).hexdigest()}",
        ]
    )
    monkeypatch.setenv("RELAY_NODE_TOKENS", "")
    monkeypatch.setenv("RELAY_NODE_TOKEN_HASHES", hashes)
    monkeypatch.setenv("RELAY_REQUIRE_HASHED_TOKENS", "true")
    get_relay_settings.cache_clear()

    with TestClient(create_app()) as hashed_client:
        assert hashed_client.get("/health").json()["auth"] == "hashed"
        for token in (old_token, new_token):
            response = hashed_client.post(
                "/v1/messages",
                json=_envelope(),
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 201
        fetched = hashed_client.get(
            "/v1/messages", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert len(fetched.json()) == 2

    get_relay_settings.cache_clear()


def test_production_auth_rejects_plaintext_tokens() -> None:
    from relay.config import RelaySettings

    settings = RelaySettings(
        node_tokens=f"{AGENT_A}=plain-token",
        require_hashed_tokens=True,
    )
    with pytest.raises(ValueError, match="RELAY_NODE_TOKENS"):
        settings.validate_auth_configuration()


def test_production_auth_requires_valid_hashes() -> None:
    from relay.config import RelaySettings

    missing = RelaySettings(require_hashed_tokens=True)
    with pytest.raises(ValueError, match="RELAY_NODE_TOKEN_HASHESが必要"):
        missing.validate_auth_configuration()

    malformed = RelaySettings(node_token_hashes=f"{AGENT_A}=not-a-sha256")
    with pytest.raises(ValueError, match="SHA-256"):
        malformed.validate_auth_configuration()


def test_same_credential_cannot_belong_to_two_agents() -> None:
    from relay.config import RelaySettings

    digest = hashlib.sha256(b"shared-token").hexdigest()
    settings = RelaySettings(
        node_token_hashes=f"{AGENT_A}={digest},{AGENT_B}={digest}"
    )
    with pytest.raises(ValueError, match="複数agent"):
        settings.validate_auth_configuration()


def test_put_fetch_ack_flow(
    client: TestClient, headers_a: dict[str, str], headers_b: dict[str, str]
) -> None:
    posted = client.post("/v1/messages", json=_envelope(), headers=headers_a)
    assert posted.status_code == 201
    delivery_id = posted.json()["delivery_id"]

    fetched = client.get("/v1/messages", headers=headers_b)
    assert fetched.status_code == 200
    items = fetched.json()
    assert len(items) == 1
    assert items[0]["delivery_id"] == delivery_id
    assert items[0]["envelope"]["message_id"] == "m001"

    acked = client.post(f"/v1/messages/{delivery_id}/ack", headers=headers_b)
    assert acked.status_code == 200
    assert client.get("/v1/messages", headers=headers_b).json() == []


def test_personal_agent_message_is_routed_by_device_node(
    client: TestClient, headers_a: dict[str, str], headers_b: dict[str, str]
) -> None:
    envelope = _envelope(sender="pa_alice", receiver="pa_bob")
    envelope["sender_node_id"] = AGENT_A
    envelope["receiver_node_id"] = AGENT_B
    posted = client.post("/v1/messages", json=envelope, headers=headers_a)
    assert posted.status_code == 201
    fetched = client.get("/v1/messages", headers=headers_b).json()
    assert fetched[0]["envelope"]["sender_agent_id"] == "pa_alice"
    assert fetched[0]["envelope"]["receiver_agent_id"] == "pa_bob"


def test_redelivery_until_ack(
    client: TestClient, headers_a: dict[str, str], headers_b: dict[str, str]
) -> None:
    client.post("/v1/messages", json=_envelope(), headers=headers_a)
    first = client.get("/v1/messages", headers=headers_b).json()
    second = client.get("/v1/messages", headers=headers_b).json()
    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["delivery_id"] == second[0]["delivery_id"]


def test_sender_must_match_token(client: TestClient, headers_b: dict[str, str]) -> None:
    response = client.post("/v1/messages", json=_envelope(sender=AGENT_A), headers=headers_b)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "RELAY_UNAUTHORIZED"


def test_unknown_receiver_rejected(client: TestClient, headers_a: dict[str, str]) -> None:
    response = client.post(
        "/v1/messages", json=_envelope(receiver="agt_unknown"), headers=headers_a
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RELAY_UNKNOWN_RECEIVER"


def test_size_limit_413(client: TestClient, headers_a: dict[str, str]) -> None:
    envelope = _envelope()
    envelope["delta"] = {"note": "x" * 4096}
    response = client.post("/v1/messages", json=envelope, headers=headers_a)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "MESSAGE_TOO_LARGE"


def test_rate_limit_429(client: TestClient, headers_a: dict[str, str]) -> None:
    for _ in range(5):
        assert (
            client.post("/v1/messages", json=_envelope(), headers=headers_a).status_code == 201
        )
    over = client.post("/v1/messages", json=_envelope(), headers=headers_a)
    assert over.status_code == 429
    assert over.json()["error"]["code"] == "RATE_LIMITED"


def test_ttl_expiry() -> None:
    from relay.store import MailboxStore

    fake_now = [1000.0]
    store = MailboxStore(ttl_seconds=60, rate_limit_per_minute=10, clock=lambda: fake_now[0])
    store.put(AGENT_B, {"message_id": "m1"})
    assert len(store.fetch(AGENT_B)) == 1

    fake_now[0] = 1061.0  # TTL経過
    assert store.fetch(AGENT_B) == []


def test_sqlite_mailbox_survives_restart(tmp_path: Path) -> None:
    from relay.store import SqliteMailboxStore

    database = tmp_path / "relay.db"
    first = SqliteMailboxStore(database, ttl_seconds=60, rate_limit_per_minute=10)
    delivery_id = first.put(AGENT_B, {"message_id": "persistent"})

    restarted = SqliteMailboxStore(database, ttl_seconds=60, rate_limit_per_minute=10)
    fetched = restarted.fetch(AGENT_B)
    assert [message.delivery_id for message in fetched] == [delivery_id]
    assert fetched[0].envelope == {"message_id": "persistent"}

    assert restarted.ack(AGENT_B, delivery_id) is True
    after_second_restart = SqliteMailboxStore(database)
    assert after_second_restart.fetch(AGENT_B) == []


def test_sqlite_ttl_and_rate_limit_survive_restart(tmp_path: Path) -> None:
    from relay.store import SqliteMailboxStore

    fake_now = [1000.0]
    database = tmp_path / "relay.db"
    first = SqliteMailboxStore(
        database,
        ttl_seconds=60,
        rate_limit_per_minute=1,
        clock=lambda: fake_now[0],
    )
    first.put(AGENT_B, {"message_id": "expires"})
    assert first.allow_send(AGENT_A) is True

    restarted = SqliteMailboxStore(
        database,
        ttl_seconds=60,
        rate_limit_per_minute=1,
        clock=lambda: fake_now[0],
    )
    assert restarted.allow_send(AGENT_A) is False
    fake_now[0] = 1060.0
    assert restarted.fetch(AGENT_B) == []
    assert restarted.allow_send(AGENT_A) is True


def test_sqlite_ack_is_scoped_to_receiver(tmp_path: Path) -> None:
    from relay.store import SqliteMailboxStore

    store = SqliteMailboxStore(tmp_path / "relay.db")
    delivery_id = store.put(AGENT_B, {"message_id": "m1"})
    assert store.ack(AGENT_A, delivery_id) is False
    assert len(store.fetch(AGENT_B)) == 1


def test_logs_do_not_contain_message_body(
    client: TestClient,
    headers_a: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="enishi.relay"):
        client.post("/v1/messages", json=_envelope(), headers=headers_a)

    assert caplog.records, "配送メタデータのログが出力されること"
    log_text = caplog.text
    assert "m001" in log_text
    assert SECRET_MARKER not in log_text
