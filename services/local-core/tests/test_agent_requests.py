from typing import Any

import pytest
from enishi_core.errors import EnishiError
from enishi_core.services.agent_requests import interpret_meeting_request
from fastapi.testclient import TestClient

_PUBLIC_KEY = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="


class _FakeRelay:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(self, envelope: dict[str, Any]) -> None:
        self.sent.append(envelope)

    def fetch(self) -> list[dict[str, Any]]:
        return []

    def ack(self, delivery_id: str) -> None:
        pass


def _user(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/v1/users", json={"display_name": "中村"}, headers=headers)
    assert response.status_code == 201
    return str(response.json()["id"])


def _activate(client: TestClient, headers: dict[str, str], user_id: str) -> None:
    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "日程調整", "provider_type": "mock"},
        headers=headers,
    ).json()
    assert client.post(f"/v1/clones/{clone['id']}/activate", headers=headers).status_code == 200


def _trusted_peer(client: TestClient, headers: dict[str, str]) -> None:
    created = client.post(
        "/v1/peers",
        json={
            "agent_id": "agt_peer_node",
            "personal_agent_id": "pa_peer",
            "display_name": "田中AI",
            "public_key": _PUBLIC_KEY,
        },
        headers=headers,
    )
    assert created.status_code == 201
    assert client.post("/v1/peers/agt_peer_node/trust", headers=headers).status_code == 200


def test_parser_accepts_only_explicit_meeting_format() -> None:
    parsed = interpret_meeting_request(
        "田中さんと2026-07-20に30分、13:00〜17:00で打ち合わせ"
    )
    assert parsed["date_range"] == {"start": "2026-07-20", "end": "2026-07-20"}
    assert parsed["duration_minutes"] == 30
    assert parsed["preferred_time_ranges"] == [{"start": "13:00", "end": "17:00"}]

    with pytest.raises(EnishiError) as exc:
        interpret_meeting_request("来週の午後に打ち合わせ")
    assert exc.value.code == "AGENT_REQUEST_AMBIGUOUS"


def test_agent_identity_exposes_stable_personal_and_device_ids(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _user(client, auth_headers)
    first = client.get(
        "/v1/agent/identity", params={"user_id": user_id}, headers=auth_headers
    )
    second = client.get(
        "/v1/agent/identity", params={"user_id": user_id}, headers=auth_headers
    )
    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["personal_agent_id"].startswith("pa_")
    assert first.json()["node_id"].startswith("agt_")


def test_ambiguous_request_does_not_send(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    relay = _FakeRelay()
    monkeypatch.setattr("enishi_core.api.routes.get_relay_client", lambda: relay)
    user_id = _user(client, auth_headers)
    _activate(client, auth_headers, user_id)
    _trusted_peer(client, auth_headers)

    response = client.post(
        "/v1/agent/requests",
        json={"user_id": user_id, "text": "来週の午後に打ち合わせ"},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AGENT_REQUEST_AMBIGUOUS"
    assert relay.sent == []


def test_agent_request_uses_personal_ids_and_node_transport_ids(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import DeviceNode, PersonalAgent

    relay = _FakeRelay()
    monkeypatch.setattr("enishi_core.api.routes.get_relay_client", lambda: relay)
    user_id = _user(client, auth_headers)
    _activate(client, auth_headers, user_id)
    _trusted_peer(client, auth_headers)

    response = client.post(
        "/v1/agent/requests",
        json={
            "user_id": user_id,
            "text": "2026-07-20に30分、13:00〜17:00で打ち合わせ",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert len(relay.sent) == 2

    session = next(get_session())
    try:
        personal = session.query(PersonalAgent).filter_by(user_id=user_id).one()
        node = session.query(DeviceNode).filter_by(personal_agent_id=personal.id).one()
    finally:
        session.close()
    for envelope in relay.sent:
        assert envelope["sender_agent_id"] == personal.id
        assert envelope["receiver_agent_id"] == "pa_peer"
        assert envelope["sender_node_id"] == node.node_id
        assert envelope["receiver_node_id"] == "agt_peer_node"


def test_agent_request_requires_active_clone(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    relay = _FakeRelay()
    monkeypatch.setattr("enishi_core.api.routes.get_relay_client", lambda: relay)
    user_id = _user(client, auth_headers)
    _trusted_peer(client, auth_headers)
    response = client.post(
        "/v1/agent/requests",
        json={
            "user_id": user_id,
            "text": "2026-07-20に30分、13:00〜17:00で打ち合わせ",
        },
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CLONE_REVIEW_REQUIRED"
    assert relay.sent == []


def test_agent_request_respects_schedule_delegation(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    relay = _FakeRelay()
    monkeypatch.setattr("enishi_core.api.routes.get_relay_client", lambda: relay)
    user_id = _user(client, auth_headers)
    _activate(client, auth_headers, user_id)
    _trusted_peer(client, auth_headers)
    updated = client.put(
        "/v1/policies/delegation",
        json={"user_id": user_id, "rules": {"schedule_negotiation": False}},
        headers=auth_headers,
    )
    assert updated.status_code == 200

    response = client.post(
        "/v1/agent/requests",
        json={
            "user_id": user_id,
            "text": "2026-07-20に30分、13:00〜17:00で打ち合わせ",
        },
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NEGOTIATION_PERMISSION_DENIED"
    assert relay.sent == []


def test_multiple_peer_candidates_require_selection_without_sending(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    relay = _FakeRelay()
    monkeypatch.setattr("enishi_core.api.routes.get_relay_client", lambda: relay)
    user_id = _user(client, auth_headers)
    _activate(client, auth_headers, user_id)
    for agent_id, name, aliases in (
        ("agt_tanaka", "田中AI", ["田中さん"]),
        ("agt_sato", "佐藤AI", ["佐藤さん"]),
    ):
        assert client.post(
            "/v1/peers",
            json={
                "agent_id": agent_id,
                "display_name": name,
                "aliases": aliases,
                "public_key": _PUBLIC_KEY,
            },
            headers=auth_headers,
        ).status_code == 201
        assert client.post(
            f"/v1/peers/{agent_id}/trust", headers=auth_headers
        ).status_code == 200

    text = "2026-07-20に30分、13:00〜17:00で打ち合わせ"
    ambiguous = client.post(
        "/v1/agent/requests",
        json={"user_id": user_id, "text": text},
        headers=auth_headers,
    )
    assert ambiguous.status_code == 422
    candidates = ambiguous.json()["error"]["details"]["candidates"]
    assert {candidate["agent_id"] for candidate in candidates} == {
        "agt_tanaka",
        "agt_sato",
    }
    assert relay.sent == []

    selected = client.post(
        "/v1/agent/requests",
        json={"user_id": user_id, "text": text, "peer_agent_id": "agt_sato"},
        headers=auth_headers,
    )
    assert selected.status_code == 201
    assert len(relay.sent) == 2


def test_agent_request_falls_back_to_legacy_wire_for_existing_peer(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    relay = _FakeRelay()
    monkeypatch.setattr("enishi_core.api.routes.get_relay_client", lambda: relay)
    user_id = _user(client, auth_headers)
    _activate(client, auth_headers, user_id)
    created = client.post(
        "/v1/peers",
        json={
            "agent_id": "agt_legacy_peer",
            "display_name": "旧形式の相手",
            "public_key": _PUBLIC_KEY,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert client.post(
        "/v1/peers/agt_legacy_peer/trust", headers=auth_headers
    ).status_code == 200

    response = client.post(
        "/v1/agent/requests",
        json={
            "user_id": user_id,
            "text": "2026-07-20に30分、13:00〜17:00で打ち合わせ",
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert len(relay.sent) == 2
    assert all("sender_node_id" not in message for message in relay.sent)
    assert all(message["receiver_agent_id"] == "agt_legacy_peer" for message in relay.sent)
