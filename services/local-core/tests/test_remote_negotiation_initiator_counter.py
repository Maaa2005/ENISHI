"""Phase G6: initiator側が相手からのPROPOSE/COUNTERを処理できることの回帰テスト。

Codexレビュー指摘の既存バグ（`main` にも同一コードで存在）:
`_handle_envelope` のPROPOSE/COUNTER分岐が「自分は常にresponder」という前提で
`negotiation.responder_agent_id` を無条件にローカル `PersonalAgent` として引いていた。
これは相手からREQUESTを受けてresponderになったセッションでは正しいが、自分が
initiatorとして開始した交渉（`start_remote_negotiation`）で相手からPROPOSE/COUNTERが
返ってきたセッションでは、そのセッションの `responder_agent_id` には相手の
personal-agent IDが入っているため、常にローカルで見つからず `CLONE_REVIEW_REQUIRED`
(409) で拒否されていた。

`cost.split` の本命テストは `test_remote_cost_split.py` に置く
（`test_cost_split_remote_initiator_processes_counter_from_peer`）。
このファイルは:
- 新規テスト2: meeting.schedule でも同じ往復（自分が開始 -> 相手がCOUNTER）が通ること
- 新規テスト3: 受信側（相手からREQUESTを受ける側）の既存挙動が変わっていないこと
- 新規テスト4: initiator側で承認エスカレーションが必要な場合、自分の所有者へ承認が
  作られること（相手の所有者ではない）
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_PUBLIC_KEY = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="

DATE_RANGE = {"start": "2026-08-03", "end": "2026-08-03"}
PREFERRED_TIME_RANGES = [{"start": "13:00", "end": "15:00"}]
DURATION_MINUTES = 30
NON_OVERLAPPING = [{"start": "2099-01-01T00:00+09:00", "end": "2099-01-01T00:30+09:00"}]


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


def _expected_candidates() -> list[dict[str, str]]:
    from enishi_core.services.scheduling import candidate_slots

    return candidate_slots(
        DATE_RANGE, PREFERRED_TIME_RANGES, DURATION_MINUTES, [], "Asia/Tokyo"
    )[:5]


# ---------------------------------------------------------------------------
# 新規テスト2: meeting.schedule でも「自分が開始 -> 相手がCOUNTER」の往復が通る。
# ---------------------------------------------------------------------------


def test_meeting_schedule_initiator_processes_counter_from_peer(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationDecision, NegotiationSession
    from enishi_core.services.remote_negotiation import process_inbox, start_remote_negotiation

    peer_identity, peer_private_key = _make_peer_identity(tmp_path)
    user_id = _user(client, auth_headers, "送信側")
    _activate_clone(client, auth_headers, user_id)
    _register_peer(
        client,
        auth_headers,
        agent_id=peer_identity.agent_id,
        personal_agent_id="pa_peer_out",
        public_key=peer_identity.public_key_b64,
    )
    local_personal_id, local_node_id = _local_ids(client, auth_headers, user_id)
    expected_candidates = _expected_candidates()

    session = next(get_session())
    relay = _FakeRelay()
    try:
        negotiation = start_remote_negotiation(
            session,
            relay,
            user_id=user_id,
            peer_agent_id=peer_identity.agent_id,
            topic="ゴールデン打ち合わせ2",
            duration_minutes=DURATION_MINUTES,
            date_range=DATE_RANGE,
            preferred_time_ranges=PREFERRED_TIME_RANGES,
        )
        session_id = negotiation.id
    finally:
        session.close()

    assert len(relay.sent) == 2
    assert relay.sent[1]["delta"] == {"candidate_slots": expected_candidates}

    # 相手は共通スロットのないCOUNTERを返してくる。
    counter_env = _build_from_peer(
        session_id=session_id,
        sequence=3,
        message_type="COUNTER",
        peer_personal_id="pa_peer_out",
        local_personal_id=local_personal_id,
        peer_node_id=peer_identity.agent_id,
        local_node_id=local_node_id,
        private_key=peer_private_key,
        delta={"candidate_slots": NON_OVERLAPPING},
    )
    relay.inbox = [{"delivery_id": "d1", "envelope": counter_env}]
    session = next(get_session())
    try:
        result = process_inbox(session, relay)
        # 修正前はここで CLONE_REVIEW_REQUIRED (409) により "rejected" になっていた。
        assert [r["action"] for r in result["results"]] == ["processed"]

        refreshed = session.get(NegotiationSession, session_id)
        assert refreshed is not None
        decision = (
            session.query(NegotiationDecision)
            .filter(NegotiationDecision.session_id == session_id)
            .first()
        )
        assert decision is not None
        assert decision.outcome == "counter"
    finally:
        session.close()

    reply_envelope = relay.sent[-1]
    assert reply_envelope["message_type"] == "COUNTER"
    assert reply_envelope["delta"] == {"candidate_slots": expected_candidates}
    assert reply_envelope["sender_agent_id"] == local_personal_id
    assert reply_envelope["receiver_agent_id"] == "pa_peer_out"


# ---------------------------------------------------------------------------
# 新規テスト3: 受信側（相手からREQUESTを受ける側）の既存挙動が変わっていないこと。
# ---------------------------------------------------------------------------


def test_meeting_schedule_responder_side_unaffected_by_g6_fix(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """`test_remote_domains.py` のゴールデンテスト1b/1cと同じシナリオを、このファイルの
    独立したセットアップでもう一度確認する（受信側=responderの経路がG6の変更で
    壊れていないことのピンポイント回帰）。ゴールデンファイル自体は変更しない。
    """
    from enishi_core.database import get_session
    from enishi_core.services.remote_negotiation import process_inbox

    peer_identity, peer_private_key = _make_peer_identity(tmp_path)
    user_id = _user(client, auth_headers, "応答側")
    _activate_clone(client, auth_headers, user_id)
    _register_peer(
        client,
        auth_headers,
        agent_id=peer_identity.agent_id,
        personal_agent_id="pa_peer",
        public_key=peer_identity.public_key_b64,
    )
    local_personal_id, local_node_id = _local_ids(client, auth_headers, user_id)
    expected_candidates = _expected_candidates()

    session_id = "remote-g6-responder-accept"
    request_env = _build_from_peer(
        session_id=session_id,
        sequence=1,
        message_type="REQUEST",
        peer_personal_id="pa_peer",
        local_personal_id=local_personal_id,
        peer_node_id=peer_identity.agent_id,
        local_node_id=local_node_id,
        private_key=peer_private_key,
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
        peer_personal_id="pa_peer",
        local_personal_id=local_personal_id,
        peer_node_id=peer_identity.agent_id,
        local_node_id=local_node_id,
        private_key=peer_private_key,
        delta={"candidate_slots": expected_candidates},
    )
    relay = _FakeRelay()
    relay.inbox = [
        {"delivery_id": "d1", "envelope": request_env},
        {"delivery_id": "d2", "envelope": propose_env},
    ]
    session = next(get_session())
    try:
        result = process_inbox(session, relay)
    finally:
        session.close()

    assert [r["action"] for r in result["results"]] == ["processed", "processed"]
    accept_envelope = relay.sent[-1]
    assert accept_envelope["message_type"] == "ACCEPT"
    assert accept_envelope["delta"] == {"selected_slot": expected_candidates[0]}


# ---------------------------------------------------------------------------
# 新規テスト4: 相手からCOUNTERが来たあと、initiator側で承認エスカレーションが
# 必要なケースは自分の所有者へ承認が作られる（相手の所有者ではない）。
# ---------------------------------------------------------------------------


def test_cost_split_initiator_escalation_creates_approval_for_own_owner(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """initiatorが委任OFFの状態でcost.splitを開始し、相手からCOUNTERを受けたとき、
    承認は initiator（自分）のuser向けに作られ、応答の送信元も自分自身の
    personal-agent IDであることを確認する。

    修正前は `negotiation.responder_agent_id`（=相手のID）決め打ちだったため、
    このケースは409で処理できず到達すらしなかった。加えて、たとえ到達できても
    `resolve_remote_approval` の `own_personal_id = negotiation.responder_agent_id`
    決め打ちのままだと、承認解決後の応答が相手のIDを送信元として送ってしまう
    （なりすまし相当のバグ）。両方が正しく直っていることを確認する。
    """
    from enishi_core.database import get_session
    from enishi_core.models import Approval, NegotiationSession, User
    from enishi_core.services.remote_negotiation import (
        flush_outbox,
        process_inbox,
        resolve_remote_approval,
        start_remote_negotiation,
    )

    peer_identity, peer_private_key = _make_peer_identity(tmp_path)
    user_id = _user(client, auth_headers, "送信側オーナー")
    _activate_clone(client, auth_headers, user_id)
    _register_peer(
        client,
        auth_headers,
        agent_id=peer_identity.agent_id,
        personal_agent_id="pa_peer_out",
        public_key=peer_identity.public_key_b64,
        capabilities={
            "timezone": "UTC",
            "supported_intents": ["cost.split"],
            "protocol_versions": ["aun/0.2"],
        },
    )
    local_personal_id, local_node_id = _local_ids(client, auth_headers, user_id)

    session = next(get_session())
    relay = _FakeRelay()
    try:
        negotiation = start_remote_negotiation(
            session,
            relay,
            user_id=user_id,
            peer_agent_id=peer_identity.agent_id,
            intent="cost.split",
            payload={
                "title": "委任OFFテスト",
                "total_amount": 10000.0,
                "currency": "JPY",
                "proposed_share": 3000.0,
                "deadline": None,
            },
        )
        session_id = negotiation.id
    finally:
        session.close()

    # 委任OFF: 開始後にOFFへ切り替え、相手からのCOUNTER受信時点で必ず
    # 承認へエスカレートさせる（開始そのものは委任ONで許可される必要があるため
    # start_remote_negotiation の後で切り替える）。
    client.put(
        "/v1/policies/delegation",
        json={"user_id": user_id, "rules": {"cost_split_negotiation": False}},
        headers=auth_headers,
    )

    counter_env = _build_from_peer(
        session_id=session_id,
        sequence=3,
        message_type="COUNTER",
        peer_personal_id="pa_peer_out",
        local_personal_id=local_personal_id,
        peer_node_id=peer_identity.agent_id,
        local_node_id=local_node_id,
        private_key=peer_private_key,
        delta={"proposed_share": 2000.0},
        intent="cost.split",
    )
    relay.inbox = [{"delivery_id": "d1", "envelope": counter_env}]
    session = next(get_session())
    approval_id: str
    try:
        result = process_inbox(session, relay)
        assert [r["action"] for r in result["results"]] == ["approval_required"]
        refreshed = session.get(NegotiationSession, session_id)
        assert refreshed is not None
        assert refreshed.status == "waiting_approval"
        assert refreshed.pending_approval_id is not None
        approval_id = refreshed.pending_approval_id

        approval = session.get(Approval, approval_id)
        assert approval is not None
        # 承認は「自分」(initiatorのuser_id)向けであり、相手のuserではない。
        assert approval.user_id == user_id
        owner = session.get(User, approval.user_id)
        assert owner is not None
        assert owner.id == user_id
    finally:
        session.close()

    session = next(get_session())
    try:
        resolve_remote_approval(session, approval_id, "approved")
        flush_outbox(session, relay)
    finally:
        session.close()

    reply_envelope = relay.sent[-1]
    # 承認解決後の応答が自分自身のpersonal-agent IDから送られていること
    # （相手のIDを名乗って送り返す誤りになっていないこと）。
    assert reply_envelope["sender_agent_id"] == local_personal_id
    assert reply_envelope["receiver_agent_id"] == "pa_peer_out"
