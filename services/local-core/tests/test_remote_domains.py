"""Phase F: 遠隔交渉のドメイン汎用化テスト（.tmp/phase-f-remote-domains-spec.md）。

テスト1は本フェーズの最強の安全網: `meeting.schedule` の遠隔交渉が生成する全エンベロープの
`payload` / `delta` のキーと値が、リファクタの前後で完全一致することを機械的に担保する。

1つの `client` fixture = 1台のノード（1本人エージェント）という制約があるため、
シナリオごとに独立したテスト関数へ分ける（`client` fixtureはfunction scope）。
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_PUBLIC_KEY = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="

DATE_RANGE = {"start": "2026-08-03", "end": "2026-08-03"}
PREFERRED_TIME_RANGES = [{"start": "13:00", "end": "15:00"}]
DURATION_MINUTES = 30


class _FakeRelay:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.inbox: list[dict[str, Any]] = []
        self.acked: list[str] = []

    def send(self, envelope: dict[str, Any]) -> None:
        self.sent.append(envelope)

    def fetch(self) -> list[dict[str, Any]]:
        return list(self.inbox)

    def ack(self, delivery_id: str) -> None:
        self.acked.append(delivery_id)


def _user(client: TestClient, headers: dict[str, str], name: str = "中村") -> str:
    response = client.post("/v1/users", json={"display_name": name}, headers=headers)
    assert response.status_code == 201
    return str(response.json()["id"])


def _activate_clone(client: TestClient, headers: dict[str, str], user_id: str) -> str:
    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "交渉", "provider_type": "mock"},
        headers=headers,
    ).json()
    assert client.post(f"/v1/clones/{clone['id']}/activate", headers=headers).status_code == 200
    return str(clone["id"])


def _register_peer(
    client: TestClient,
    headers: dict[str, str],
    *,
    agent_id: str,
    personal_agent_id: str | None = None,
    public_key: str = _PUBLIC_KEY,
    capabilities: dict[str, Any] | None = None,
) -> None:
    body: dict[str, Any] = {
        "agent_id": agent_id,
        "display_name": "相手AI",
        "public_key": public_key,
    }
    if personal_agent_id is not None:
        body["personal_agent_id"] = personal_agent_id
    if capabilities is not None:
        body["capabilities"] = capabilities
    created = client.post("/v1/peers", json=body, headers=headers)
    assert created.status_code == 201, created.text
    trusted = client.post(f"/v1/peers/{agent_id}/trust", headers=headers)
    assert trusted.status_code == 200


def _envelope_shape(envelope: dict[str, Any]) -> dict[str, Any]:
    """wire互換の担保対象だけを抜き出す（message_id/nonce/created_at/署名等は除く）。"""
    return {
        "message_type": envelope["message_type"],
        "intent": envelope["intent"],
        "payload": envelope["payload"],
        "delta": envelope["delta"],
    }


def _make_peer_identity(tmp_path: Path, name: str = "peer") -> tuple[Any, Any]:
    from enishi_core.security.keys import ensure_node_keypair

    return ensure_node_keypair(tmp_path / name)


def _local_ids(client: TestClient, headers: dict[str, str], user_id: str) -> tuple[str, str]:
    response = client.get(
        "/v1/agent/identity", params={"user_id": user_id}, headers=headers
    )
    assert response.status_code == 200, response.text
    identity = response.json()
    return str(identity["personal_agent_id"]), str(identity["node_id"])


def _build_from_peer(
    *,
    session_id: str,
    sequence: int,
    message_type: str,
    peer_personal_id: str,
    local_personal_id: str,
    peer_node_id: str,
    local_node_id: str,
    private_key: Any,
    delta: dict[str, Any],
    payload: dict[str, Any] | None = None,
    intent: str = "meeting.schedule",
) -> dict[str, Any]:
    from enishi_core.security.envelope import build_envelope

    return build_envelope(
        sender=peer_personal_id,
        receiver=local_personal_id,
        session_id=session_id,
        message_type=message_type,
        intent=intent,
        session_version=1,
        sequence=sequence,
        payload=payload or {},
        delta=delta,
        requires_human_approval=False,
        private_key=private_key,
        sender_node_id=peer_node_id,
        receiver_node_id=local_node_id,
    )


def _setup_local_responder(
    client: TestClient,
    headers: dict[str, str],
    tmp_path: Path,
    *,
    delegation_enabled: bool = True,
) -> tuple[str, str, str, Any]:
    """相手ノード（peer）と、応答側になるローカルユーザーをセットアップする。"""
    peer_identity, peer_private_key = _make_peer_identity(tmp_path)
    user_id = _user(client, headers, "応答側")
    _activate_clone(client, headers, user_id)
    if not delegation_enabled:
        client.put(
            "/v1/policies/delegation",
            json={"user_id": user_id, "rules": {"schedule_negotiation": False}},
            headers=headers,
        )
    _register_peer(
        client,
        headers,
        agent_id=peer_identity.agent_id,
        personal_agent_id="pa_peer",
        public_key=peer_identity.public_key_b64,
    )
    local_personal_id, local_node_id = _local_ids(client, headers, user_id)
    return local_personal_id, local_node_id, peer_identity.agent_id, peer_private_key


def _request_and_propose_from_peer(
    session_id: str,
    peer_personal_id: str,
    local_personal_id: str,
    peer_node_id: str,
    local_node_id: str,
    private_key: Any,
    offered_slots: list[dict[str, str]],
) -> list[dict[str, Any]]:
    request_env = _build_from_peer(
        session_id=session_id,
        sequence=1,
        message_type="REQUEST",
        peer_personal_id=peer_personal_id,
        local_personal_id=local_personal_id,
        peer_node_id=peer_node_id,
        local_node_id=local_node_id,
        private_key=private_key,
        delta={},
        payload={
            "intent": "meeting.schedule",
            "topic": "受信側テスト",
            "duration_minutes": DURATION_MINUTES,
            "date_range": DATE_RANGE,
            "preferred_time_ranges": PREFERRED_TIME_RANGES,
            "timezone": "Asia/Tokyo",
        },
    )
    propose_env = _build_from_peer(
        session_id=session_id,
        sequence=2,
        message_type="PROPOSE",
        peer_personal_id=peer_personal_id,
        local_personal_id=local_personal_id,
        peer_node_id=peer_node_id,
        local_node_id=local_node_id,
        private_key=private_key,
        delta={"candidate_slots": offered_slots},
    )
    return [request_env, propose_env]


def _expected_candidates() -> list[dict[str, str]]:
    from enishi_core.services.scheduling import candidate_slots

    return candidate_slots(
        DATE_RANGE, PREFERRED_TIME_RANGES, DURATION_MINUTES, [], "Asia/Tokyo"
    )[:5]


def test_meeting_schedule_wire_request_propose_golden(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """テスト1a: 送信側（initiator）が生成するREQUEST/PROPOSEのwire形。"""
    from enishi_core.database import get_session
    from enishi_core.services.remote_negotiation import start_remote_negotiation

    peer_identity, _peer_priv = _make_peer_identity(tmp_path)
    user_id = _user(client, auth_headers, "送信側")
    _activate_clone(client, auth_headers, user_id)
    _register_peer(
        client,
        auth_headers,
        agent_id=peer_identity.agent_id,
        personal_agent_id="pa_peer_out",
        public_key=peer_identity.public_key_b64,
    )

    session = next(get_session())
    relay = _FakeRelay()
    try:
        start_remote_negotiation(
            session,
            relay,
            user_id=user_id,
            peer_agent_id=peer_identity.agent_id,
            topic="ゴールデン打ち合わせ",
            duration_minutes=DURATION_MINUTES,
            date_range=DATE_RANGE,
            preferred_time_ranges=PREFERRED_TIME_RANGES,
        )
    finally:
        session.close()

    assert len(relay.sent) == 2
    assert _envelope_shape(relay.sent[0]) == {
        "message_type": "REQUEST",
        "intent": "meeting.schedule",
        "payload": {
            "intent": "meeting.schedule",
            "topic": "ゴールデン打ち合わせ",
            "duration_minutes": DURATION_MINUTES,
            "date_range": DATE_RANGE,
            "preferred_time_ranges": PREFERRED_TIME_RANGES,
            "timezone": "Asia/Tokyo",
        },
        "delta": {},
    }
    assert _envelope_shape(relay.sent[1]) == {
        "message_type": "PROPOSE",
        "intent": "meeting.schedule",
        "payload": {},
        "delta": {"candidate_slots": _expected_candidates()},
    }


def test_meeting_schedule_wire_accept_on_common_slot_golden(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """テスト1b: 応答側で共通スロットが見つかりACCEPTを返すwire形。"""
    from enishi_core.database import get_session
    from enishi_core.services.remote_negotiation import process_inbox

    local_personal_id, local_node_id, peer_agent_id, peer_priv = _setup_local_responder(
        client, auth_headers, tmp_path
    )
    expected_candidates = _expected_candidates()
    session_id = "remote-golden-session-accept"
    relay = _FakeRelay()
    relay.inbox = [
        {"delivery_id": "d1", "envelope": env}
        for env in _request_and_propose_from_peer(
            session_id,
            "pa_peer",
            local_personal_id,
            peer_agent_id,
            local_node_id,
            peer_priv,
            expected_candidates,
        )
    ]
    session = next(get_session())
    try:
        result = process_inbox(session, relay)
    finally:
        session.close()
    assert [r["action"] for r in result["results"]] == ["processed", "processed"]
    accept_envelope = relay.sent[-1]
    assert _envelope_shape(accept_envelope) == {
        "message_type": "ACCEPT",
        "intent": "meeting.schedule",
        "payload": {},
        "delta": {"selected_slot": expected_candidates[0]},
    }


def test_meeting_schedule_wire_counter_no_common_slot_golden(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """テスト1c: 共通スロットがない場合のCOUNTER-from-usのwire形。"""
    from enishi_core.database import get_session
    from enishi_core.services.remote_negotiation import process_inbox

    local_personal_id, local_node_id, peer_agent_id, peer_priv = _setup_local_responder(
        client, auth_headers, tmp_path
    )
    expected_candidates = _expected_candidates()
    non_overlapping = [{"start": "2099-01-01T00:00+09:00", "end": "2099-01-01T00:30+09:00"}]
    session_id = "remote-golden-session-counter"
    relay = _FakeRelay()
    relay.inbox = [
        {"delivery_id": "d1", "envelope": env}
        for env in _request_and_propose_from_peer(
            session_id,
            "pa_peer",
            local_personal_id,
            peer_agent_id,
            local_node_id,
            peer_priv,
            non_overlapping,
        )
    ]
    session = next(get_session())
    try:
        process_inbox(session, relay)
    finally:
        session.close()
    counter_envelope = relay.sent[-1]
    assert _envelope_shape(counter_envelope) == {
        "message_type": "COUNTER",
        "intent": "meeting.schedule",
        "payload": {"public_reason": "no_common_slot"},
        "delta": {"candidate_slots": expected_candidates},
    }


def _run_approval_scenario(
    client: TestClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    *,
    resolution: str,
) -> dict[str, Any]:
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationSession
    from enishi_core.services.remote_negotiation import (
        flush_outbox,
        process_inbox,
        resolve_remote_approval,
    )

    local_personal_id, local_node_id, peer_agent_id, peer_priv = _setup_local_responder(
        client, auth_headers, tmp_path, delegation_enabled=False
    )
    expected_candidates = _expected_candidates()
    session_id = f"remote-golden-session-approval-{resolution}"
    relay = _FakeRelay()
    relay.inbox = [
        {"delivery_id": "d1", "envelope": env}
        for env in _request_and_propose_from_peer(
            session_id,
            "pa_peer",
            local_personal_id,
            peer_agent_id,
            local_node_id,
            peer_priv,
            expected_candidates,
        )
    ]
    session = next(get_session())
    try:
        result = process_inbox(session, relay)
        assert [r["action"] for r in result["results"]] == ["processed", "approval_required"]
        refreshed = session.get(NegotiationSession, session_id)
        assert refreshed is not None
        approval_id = refreshed.pending_approval_id
        assert approval_id is not None

        if resolution == "approve":
            resolve_remote_approval(session, approval_id, "approved")
        elif resolution == "override":
            resolve_remote_approval(
                session,
                approval_id,
                "approved",
                selected_slot_override=expected_candidates[1],
            )
        else:
            resolve_remote_approval(session, approval_id, "rejected")
        flush_outbox(session, relay)
    finally:
        session.close()
    return {"envelope": relay.sent[-1], "expected_candidates": expected_candidates}


def test_meeting_schedule_wire_approval_accept_golden(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """テスト1d: 承認->ACCEPTのwire形。"""
    outcome = _run_approval_scenario(client, auth_headers, tmp_path, resolution="approve")
    assert _envelope_shape(outcome["envelope"]) == {
        "message_type": "ACCEPT",
        "intent": "meeting.schedule",
        "payload": {},
        "delta": {"selected_slot": outcome["expected_candidates"][0]},
    }


def test_meeting_schedule_wire_approval_override_counter_golden(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """テスト1e: 承認時の候補上書き->COUNTERのwire形。"""
    outcome = _run_approval_scenario(client, auth_headers, tmp_path, resolution="override")
    assert _envelope_shape(outcome["envelope"]) == {
        "message_type": "COUNTER",
        "intent": "meeting.schedule",
        "payload": {"public_reason": "policy_declined"},
        "delta": {"candidate_slots": [outcome["expected_candidates"][1]]},
    }


def test_meeting_schedule_wire_approval_reject_golden(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """テスト1f: 承認拒否->REJECTのwire形。"""
    outcome = _run_approval_scenario(client, auth_headers, tmp_path, resolution="reject")
    assert _envelope_shape(outcome["envelope"]) == {
        "message_type": "REJECT",
        "intent": "meeting.schedule",
        "payload": {"public_reason": "policy_declined"},
        "delta": {"code": "HUMAN_REJECTED"},
    }
