import logging

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
