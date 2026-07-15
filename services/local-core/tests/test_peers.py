import base64

from fastapi.testclient import TestClient

_PUBLIC_KEY = base64.b64encode(b"\x01" * 32).decode("ascii")


def _register(client: TestClient, headers: dict[str, str], agent_id: str = "agt_peer1") -> dict:
    response = client.post(
        "/v1/peers",
        json={"agent_id": agent_id, "display_name": "田中のクローン", "public_key": _PUBLIC_KEY},
        headers=headers,
    )
    assert response.status_code == 201
    return dict(response.json())


def test_register_and_trust_flow(client: TestClient, auth_headers: dict[str, str]) -> None:
    peer = _register(client, auth_headers)
    assert peer["status"] == "pending"
    assert ":" in peer["fingerprint"]

    trusted = client.post(f"/v1/peers/{peer['agent_id']}/trust", headers=auth_headers)
    assert trusted.status_code == 200
    assert trusted.json()["status"] == "trusted"

    listed = client.get("/v1/peers", headers=auth_headers)
    assert [p["agent_id"] for p in listed.json()] == [peer["agent_id"]]


def test_duplicate_registration_409(client: TestClient, auth_headers: dict[str, str]) -> None:
    _register(client, auth_headers)
    duplicate = client.post(
        "/v1/peers",
        json={"agent_id": "agt_peer1", "display_name": "重複", "public_key": _PUBLIC_KEY},
        headers=auth_headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_trust_unknown_peer_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/v1/peers/agt_unknown/trust", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PEER_NOT_FOUND"


def test_blocked_peer_cannot_be_trusted(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    peer = _register(client, auth_headers)
    blocked = client.post(f"/v1/peers/{peer['agent_id']}/block", headers=auth_headers)
    assert blocked.json()["status"] == "blocked"

    trust = client.post(f"/v1/peers/{peer['agent_id']}/trust", headers=auth_headers)
    assert trust.status_code == 409
    assert trust.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_audit_log_has_fingerprint_but_not_public_key(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import AuditLog
    from sqlalchemy import select

    peer = _register(client, auth_headers)
    client.post(f"/v1/peers/{peer['agent_id']}/trust", headers=auth_headers)

    session = next(get_session())
    try:
        events = list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.event_type.in_(["peer_registered", "peer_trusted"])
                )
            )
        )
    finally:
        session.close()

    assert {e.event_type for e in events} == {"peer_registered", "peer_trusted"}
    for event in events:
        assert event.payload["fingerprint"] == peer["fingerprint"]
        assert _PUBLIC_KEY not in str(event.payload)
