"""Phase G5: 承認解決APIの入力スキーマ汎用化テスト。

Codexレビューで指摘された穴: 承認APIが `selected_slot` しか受け取れず、
cost.split の `agreed_share` 上書きをAPIから指定できなかった（8000円の提案を
6000円へ人間が修正して承認したつもりでも、API上は6000円を表現できず8000円で
ACCEPTされる）。

`ApprovalResolutionRequest`（schemas/__init__.py）にドメイン非依存の
`proposal_override` を追加し、`selected_slot` は後方互換として引き続き受理する
（`NegotiationCreate` / `RemoteNegotiationCreate` と同じ処方）。このテストは
API エンドポイント（`POST /v1/approvals/{id}/approve`）をend-to-endで叩いて、
上書きが実際にAgreementへ反映されることを確認する。

`tests/test_remote_domains.py`（ゴールデン）は変更しない。ヘルパーは
`test_remote_approval_payload.py` / `test_remote_cost_split.py` と同じ形を
このファイルへ複製する（依存を作らない方針を踏襲）。
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


def _user(client: TestClient, headers: dict[str, str], name: str = "本人") -> str:
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
) -> None:
    body: dict[str, Any] = {
        "agent_id": agent_id,
        "display_name": "相手AI",
        "public_key": public_key,
    }
    if personal_agent_id is not None:
        body["personal_agent_id"] = personal_agent_id
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
    intent: str,
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


def _setup_cost_split_pending_approval(
    client: TestClient, headers: dict[str, str], tmp_path: Path, session_id: str
) -> str:
    """相手から8000円の分担提案を受け、委任OFFで承認待ちにする。戻り値はapproval_id。"""
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationSession
    from enishi_core.services.remote_negotiation import process_inbox

    peer_identity, peer_priv = _make_peer_identity(tmp_path)
    user_id = _user(client, headers)
    _activate_clone(client, headers, user_id)
    client.put(
        "/v1/policies/delegation",
        json={"user_id": user_id, "rules": {"cost_split_negotiation": False}},
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

    relay = _FakeRelay()
    relay.inbox = [
        {"delivery_id": "d1", "envelope": env}
        for env in [
            _build_from_peer(
                session_id=session_id,
                sequence=1,
                message_type="REQUEST",
                peer_personal_id="pa_peer",
                local_personal_id=local_personal_id,
                peer_node_id=peer_identity.agent_id,
                local_node_id=local_node_id,
                private_key=peer_priv,
                delta={},
                payload={
                    "intent": "cost.split",
                    "title": "proposal_override検証",
                    "total_amount": 10000.0,
                    "currency": "JPY",
                    "proposed_share": 8000.0,
                    "deadline": None,
                },
                intent="cost.split",
            ),
            _build_from_peer(
                session_id=session_id,
                sequence=2,
                message_type="PROPOSE",
                peer_personal_id="pa_peer",
                local_personal_id=local_personal_id,
                peer_node_id=peer_identity.agent_id,
                local_node_id=local_node_id,
                private_key=peer_priv,
                delta={"proposed_share": 8000.0},
                intent="cost.split",
            ),
        ]
    ]
    session = next(get_session())
    try:
        result = process_inbox(session, relay)
        assert [r["action"] for r in result["results"]] == ["processed", "approval_required"]
        negotiation = session.get(NegotiationSession, session_id)
        assert negotiation is not None
        approval_id = negotiation.pending_approval_id
        assert approval_id is not None
        return str(approval_id)
    finally:
        session.close()


def _expected_candidates() -> list[dict[str, str]]:
    from enishi_core.services.scheduling import candidate_slots

    return candidate_slots(
        DATE_RANGE, PREFERRED_TIME_RANGES, DURATION_MINUTES, [], "Asia/Tokyo"
    )[:5]


def _setup_meeting_pending_approval(
    client: TestClient, headers: dict[str, str], tmp_path: Path, session_id: str
) -> tuple[str, list[dict[str, str]]]:
    """相手からmeeting.scheduleのREQUEST/PROPOSEを受け、委任OFFで承認待ちにする。"""
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationSession
    from enishi_core.services.remote_negotiation import process_inbox

    peer_identity, peer_priv = _make_peer_identity(tmp_path)
    user_id = _user(client, headers, "meeting本人")
    _activate_clone(client, headers, user_id)
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
    expected_candidates = _expected_candidates()

    relay = _FakeRelay()
    relay.inbox = [
        {"delivery_id": "d1", "envelope": env}
        for env in [
            _build_from_peer(
                session_id=session_id,
                sequence=1,
                message_type="REQUEST",
                peer_personal_id="pa_peer",
                local_personal_id=local_personal_id,
                peer_node_id=peer_identity.agent_id,
                local_node_id=local_node_id,
                private_key=peer_priv,
                delta={},
                payload={
                    "intent": "meeting.schedule",
                    "topic": "proposal_override後方互換検証",
                    "duration_minutes": DURATION_MINUTES,
                    "date_range": DATE_RANGE,
                    "preferred_time_ranges": PREFERRED_TIME_RANGES,
                    "timezone": "Asia/Tokyo",
                },
                intent="meeting.schedule",
            ),
            _build_from_peer(
                session_id=session_id,
                sequence=2,
                message_type="PROPOSE",
                peer_personal_id="pa_peer",
                local_personal_id=local_personal_id,
                peer_node_id=peer_identity.agent_id,
                local_node_id=local_node_id,
                private_key=peer_priv,
                delta={"candidate_slots": expected_candidates},
                intent="meeting.schedule",
            ),
        ]
    ]
    session = next(get_session())
    try:
        result = process_inbox(session, relay)
        assert [r["action"] for r in result["results"]] == ["processed", "approval_required"]
        negotiation = session.get(NegotiationSession, session_id)
        assert negotiation is not None
        approval_id = negotiation.pending_approval_id
        assert approval_id is not None
        return str(approval_id), expected_candidates
    finally:
        session.close()


def _outbox_latest_delta(session_id: str) -> dict[str, Any]:
    """OutboxへACCEPTとして積まれた最新envelopeのdeltaを返す。"""
    from enishi_core.database import get_session
    from enishi_core.models import RelayOutbox

    session = next(get_session())
    try:
        items = (
            session.query(RelayOutbox)
            .filter(RelayOutbox.session_id == session_id)
            .order_by(RelayOutbox.created_at.desc())
            .all()
        )
        assert items, "outboxに何も積まれていない"
        return dict(items[0].envelope["delta"])
    finally:
        session.close()


def _negotiation_status(session_id: str) -> str:
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationSession

    session = next(get_session())
    try:
        negotiation = session.get(NegotiationSession, session_id)
        assert negotiation is not None
        return str(negotiation.status)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 新規テスト1（本命）: cost.split の遠隔交渉で proposal_override により金額を
# 修正して承認すると、修正後の金額でAgreementが成立する。
# ---------------------------------------------------------------------------


def test_cost_split_approval_override_via_api_uses_corrected_amount(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    session_id = "g5-cost-split-override"
    approval_id = _setup_cost_split_pending_approval(client, auth_headers, tmp_path, session_id)

    response = client.post(
        f"/v1/approvals/{approval_id}/approve",
        json={"proposal_override": {"agreed_share": 6000.0}},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"

    delta = _outbox_latest_delta(session_id)
    assert delta["agreed_share"] == 6000.0
    assert delta["agreed_share"] != 8000.0
    assert _negotiation_status(session_id) == "agreed"


# ---------------------------------------------------------------------------
# 新規テスト2（後方互換）: meeting.schedule の selected_slot 形式の上書きは
# 従来どおりAPI経由で動く。
# ---------------------------------------------------------------------------


def test_meeting_selected_slot_override_via_api_still_works(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    session_id = "g5-meeting-selected-slot-legacy"
    approval_id, expected_candidates = _setup_meeting_pending_approval(
        client, auth_headers, tmp_path, session_id
    )
    overridden_slot = expected_candidates[1]

    response = client.post(
        f"/v1/approvals/{approval_id}/approve",
        json={"selected_slot": overridden_slot},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    # meeting.schedule のドメイン挙動（test_remote_domains.py の
    # test_meeting_schedule_wire_approval_override_counter_golden と同じ):
    # 元々選ばれていた候補と異なるスロットへ上書きすると、相手はまだそのスロットに
    # 合意していないためACCEPTではなくCOUNTERとして送信される。ここでは
    # 「selected_slot の上書きがAPI経由で反映されること」を確認する。
    delta = _outbox_latest_delta(session_id)
    assert delta["candidate_slots"] == [overridden_slot]
    assert overridden_slot != expected_candidates[0]


# ---------------------------------------------------------------------------
# 新規テスト3: 上書きなしの承認は従来どおり、提案どおりの内容で成立する。
# ---------------------------------------------------------------------------


def test_cost_split_approval_without_override_keeps_proposed_amount(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    session_id = "g5-cost-split-no-override"
    approval_id = _setup_cost_split_pending_approval(client, auth_headers, tmp_path, session_id)

    response = client.post(
        f"/v1/approvals/{approval_id}/approve",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    delta = _outbox_latest_delta(session_id)
    assert delta["agreed_share"] == 8000.0
    assert _negotiation_status(session_id) == "agreed"


# ---------------------------------------------------------------------------
# 新規テスト4: ドメインが受け付けない形の proposal_override は、黙って元の値で
# 成立させず、決定的にエラーで拒否される。
# ---------------------------------------------------------------------------


def test_cost_split_invalid_override_is_rejected_decisively(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    session_id = "g5-cost-split-invalid-override"
    approval_id = _setup_cost_split_pending_approval(client, auth_headers, tmp_path, session_id)

    response = client.post(
        f"/v1/approvals/{approval_id}/approve",
        # cost.split は `agreed_share` を要求する。無関係なキーだけの上書きは
        # 「表現できない上書き」であり、黙って元の8000円で成立してはいけない。
        json={"proposal_override": {"note": "6000円のつもり"}},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "INVALID_APPROVAL_SELECTION"

    # 承認・交渉は解決されずに残っている（黙って元の金額で確定していない）。
    assert _negotiation_status(session_id) == "waiting_approval"
    from enishi_core.database import get_session
    from enishi_core.models import Approval

    session = next(get_session())
    try:
        approval = session.get(Approval, approval_id)
        assert approval is not None
        assert approval.status == "pending"
    finally:
        session.close()
