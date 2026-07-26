"""Phase F5-b: `cost.split` の遠隔交渉ドライバ実装のテスト（.tmp/phase-f5-spec.md 新規テスト1〜6）。

`test_remote_domains.py`（meeting.schedule のワイヤ形状ゴールデンテスト）と対になる、
`cost.split` 専用のテストファイル。`test_remote_domains.py` 自体は1行も変更しない
（あちらの golden test は不変条件）。

新規テスト4（名刺に cost.split が載る）は `test_identity_card_capabilities.py` の
更新（本フェーズで実施済み）でカバー済みのため、ここでは重複させない。
"""

from pathlib import Path
from typing import Any

import pytest
from enishi_core.services.intent_interpreter import InterpretedRequest
from fastapi.testclient import TestClient

_PUBLIC_KEY = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="

_FORBIDDEN_KEYS = {
    "reservation_ratio",
    "preferred_ratio",
    "concession_ratio",
    "max_auto_accept_amount",
    "max_negotiable_amount",
}

_V2_COST_SPLIT_CAPABILITIES = {
    "timezone": "UTC",
    "supported_intents": ["cost.split"],
    "protocol_versions": ["aun/0.2"],
}


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
        json={"purpose": "割り勘", "provider_type": "mock"},
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
    intent: str = "cost.split",
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
) -> tuple[str, str, str, Any, str]:
    """相手ノード（peer）と、応答側になるローカルユーザーをセットアップする。

    戻り値: (local_personal_id, local_node_id, peer_agent_id, peer_private_key, clone_id)
    """
    peer_identity, peer_private_key = _make_peer_identity(tmp_path)
    user_id = _user(client, headers, "応答側")
    clone_id = _activate_clone(client, headers, user_id)
    if not delegation_enabled:
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
    return local_personal_id, local_node_id, peer_identity.agent_id, peer_private_key, clone_id


def _set_cost_split_profile(
    clone_id: str,
    *,
    policy: dict[str, Any] | None = None,
    preference: dict[str, Any] | None = None,
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import CloneAgent

    session = next(get_session())
    try:
        clone = session.get(CloneAgent, clone_id)
        assert clone is not None
        if policy is not None:
            clone.policy_profile = {**clone.policy_profile, "cost_split": policy}
        if preference is not None:
            clone.preference_profile = {**clone.preference_profile, "cost_split": preference}
        session.commit()
    finally:
        session.close()


def _request_and_propose_from_peer(
    session_id: str,
    peer_personal_id: str,
    local_personal_id: str,
    peer_node_id: str,
    local_node_id: str,
    private_key: Any,
    *,
    total_amount: float,
    proposed_share: float,
    title: str = "受信側テスト割り勘",
    currency: str = "JPY",
    deadline: str | None = None,
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
            "intent": "cost.split",
            "title": title,
            "total_amount": total_amount,
            "currency": currency,
            "proposed_share": proposed_share,
            "deadline": deadline,
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
        delta={"proposed_share": proposed_share},
    )
    return [request_env, propose_env]


def _find_forbidden_keys(value: Any, path: str = "$") -> list[str]:
    """dict/listを再帰的に走査し、禁止キーが現れたパスの一覧を返す。"""
    found: list[str] = []
    if isinstance(value, dict):
        for key, sub in value.items():
            if key in _FORBIDDEN_KEYS:
                found.append(f"{path}.{key}")
            found.extend(_find_forbidden_keys(sub, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_forbidden_keys(item, f"{path}[{index}]"))
    return found


def _all_negotiation_message_bodies(session_id: str) -> list[dict[str, Any]]:
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationMessage

    session = next(get_session())
    try:
        messages = session.query(NegotiationMessage).filter(
            NegotiationMessage.session_id == session_id
        ).all()
        return [{"payload": dict(m.payload), "delta": dict(m.delta)} for m in messages]
    finally:
        session.close()


def _get_approval_payload(approval_id: str) -> dict[str, Any]:
    from enishi_core.database import get_session
    from enishi_core.models import Approval

    session = next(get_session())
    try:
        approval = session.get(Approval, approval_id)
        assert approval is not None
        return dict(approval.payload)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 新規テスト1: 遠隔 cost.split が最後まで走る（往路REQUEST/PROPOSE + 復路ACCEPT）。
# ---------------------------------------------------------------------------


def test_cost_split_remote_round_trip_reaches_agreement(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """送信側が v2 ピア（supported_intents に cost.split を宣言）へ遠隔依頼し、
    相手のACCEPTを受け取って合意に至るまでの一連の流れ。
    """
    from enishi_core.database import get_session
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
        capabilities=_V2_COST_SPLIT_CAPABILITIES,
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
                "title": "飲み会の割り勘",
                "total_amount": 10000.0,
                "currency": "JPY",
                "proposed_share": 3000.0,
                "deadline": None,
            },
        )
        session_id = negotiation.id
    finally:
        session.close()

    assert len(relay.sent) == 2
    assert _envelope_shape(relay.sent[0]) == {
        "message_type": "REQUEST",
        "intent": "cost.split",
        "payload": {
            "intent": "cost.split",
            "title": "飲み会の割り勘",
            "total_amount": 10000.0,
            "currency": "JPY",
            "proposed_share": 3000.0,
            "deadline": None,
        },
        "delta": {},
    }
    assert relay.sent[1]["message_type"] == "PROPOSE"
    assert relay.sent[1]["delta"] == {"proposed_share": 3000.0}

    # 相手が即ACCEPTしたと仮定し、返信を受信する。
    accept_env = _build_from_peer(
        session_id=session_id,
        sequence=3,
        message_type="ACCEPT",
        peer_personal_id="pa_peer_out",
        local_personal_id=local_personal_id,
        peer_node_id=peer_identity.agent_id,
        local_node_id=local_node_id,
        private_key=peer_private_key,
        delta={"agreed_share": 3000.0},
    )
    relay.inbox = [{"delivery_id": "d1", "envelope": accept_env}]
    session = next(get_session())
    try:
        result = process_inbox(session, relay)
        assert [r["action"] for r in result["results"]] == ["processed"]
        from enishi_core.models import Agreement, NegotiationSession

        refreshed = session.get(NegotiationSession, session_id)
        assert refreshed is not None
        assert refreshed.status == "agreed"
        agreement = session.query(Agreement).filter(
            Agreement.session_id == session_id
        ).first()
        assert agreement is not None
        assert agreement.agreed_payload == {
            "intent": "cost.split",
            "title": "飲み会の割り勘",
            "total_amount": 10000.0,
            "currency": "JPY",
            "agreed_share": 3000.0,
            "deadline": None,
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 新規テスト1（応答側）: REQUEST+PROPOSEを受信し、自動でACCEPTを返す（`next_action`経由）。
# ---------------------------------------------------------------------------


def test_cost_split_remote_responder_auto_accepts_within_position(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    local_personal_id, local_node_id, peer_agent_id, peer_priv, _clone_id = (
        _setup_local_responder(client, auth_headers, tmp_path)
    )
    session_id = "remote-cost-split-auto-accept"
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
            total_amount=10000.0,
            proposed_share=3000.0,
        )
    ]
    from enishi_core.database import get_session
    from enishi_core.services.remote_negotiation import process_inbox

    session = next(get_session())
    try:
        result = process_inbox(session, relay)
    finally:
        session.close()

    assert [r["action"] for r in result["results"]] == ["processed", "processed"]
    accept_envelope = relay.sent[-1]
    assert _envelope_shape(accept_envelope) == {
        "message_type": "ACCEPT",
        "intent": "cost.split",
        "payload": {},
        "delta": {"agreed_share": 3000.0},
    }


# ---------------------------------------------------------------------------
# 新規テスト: 複数ラウンド（COUNTER→ACCEPT）でも `next_action` がそのまま使えること、
# かつ全メッセージに禁止キー（留保価格等）が一切現れないこと（新規テスト2の中核）。
# ---------------------------------------------------------------------------


def test_cost_split_remote_counter_then_accept_never_leaks_private_policy(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    local_personal_id, local_node_id, peer_agent_id, peer_priv, clone_id = (
        _setup_local_responder(client, auth_headers, tmp_path)
    )
    # opening(x_r)=3000 < standing(4000) <= reservation(5000) となるよう、
    # preferred_ratio をデフォルト(0.5)より下げてCOUNTERが発生する状況を作る。
    _set_cost_split_profile(clone_id, preference={"preferred_ratio": 0.3})

    session_id = "remote-cost-split-counter-then-accept"
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
            total_amount=10000.0,
            proposed_share=4000.0,
        )
    ]
    from enishi_core.database import get_session
    from enishi_core.services.remote_negotiation import process_inbox

    session = next(get_session())
    try:
        result = process_inbox(session, relay)
    finally:
        session.close()
    assert [r["action"] for r in result["results"]] == ["processed", "processed"]
    counter_envelope = relay.sent[-1]
    assert _envelope_shape(counter_envelope) == {
        "message_type": "COUNTER",
        "intent": "cost.split",
        "payload": {"public_reason": "constraint_violation"},
        "delta": {"proposed_share": 3500.0},
    }

    # 相手が、こちらの直近COUNTER(3500)にそのまま合わせて再提示してきた（第2ラウンド）。
    second_round_env = _build_from_peer(
        session_id=session_id,
        sequence=4,
        message_type="COUNTER",
        peer_personal_id="pa_peer",
        local_personal_id=local_personal_id,
        peer_node_id=peer_agent_id,
        local_node_id=local_node_id,
        private_key=peer_priv,
        delta={"proposed_share": 3500.0},
    )
    relay.inbox = [{"delivery_id": "d2", "envelope": second_round_env}]
    session = next(get_session())
    try:
        result = process_inbox(session, relay)
    finally:
        session.close()
    assert [r["action"] for r in result["results"]] == ["processed"]
    accept_envelope = relay.sent[-1]
    assert _envelope_shape(accept_envelope) == {
        "message_type": "ACCEPT",
        "intent": "cost.split",
        "payload": {},
        "delta": {"agreed_share": 3500.0},
    }

    # 新規テスト2: このセッションで生成された全メッセージのpayload/deltaを再帰走査し、
    # 留保価格・効用パラメータが一度も出ていないことを機械的に確認する。
    bodies = _all_negotiation_message_bodies(session_id)
    # REQUEST, PROPOSE(from peer), COUNTER(from local), COUNTER(from peer), ACCEPT(from local)
    assert len(bodies) == 5
    all_leaks: list[str] = []
    for body in bodies:
        all_leaks.extend(_find_forbidden_keys(body["payload"]))
        all_leaks.extend(_find_forbidden_keys(body["delta"]))
    for sent in relay.sent:
        all_leaks.extend(_find_forbidden_keys(sent["payload"]))
        all_leaks.extend(_find_forbidden_keys(sent["delta"]))
    assert all_leaks == []


# ---------------------------------------------------------------------------
# 新規テスト3: 留保価格を超える提示は承認へエスカレートし、承認payloadにも
# 禁止キーが一切現れないこと。
# ---------------------------------------------------------------------------


def test_cost_split_remote_escalates_to_approval_without_leaking_reservation(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    local_personal_id, local_node_id, peer_agent_id, peer_priv, _clone_id = (
        _setup_local_responder(client, auth_headers, tmp_path)
    )
    session_id = "remote-cost-split-escalate"
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
            total_amount=10000.0,
            proposed_share=8000.0,  # デフォルトのreservation(5000)を超える
        )
    ]
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationSession
    from enishi_core.services.remote_negotiation import (
        flush_outbox,
        process_inbox,
        resolve_remote_approval,
    )

    session = next(get_session())
    try:
        result = process_inbox(session, relay)
        assert [r["action"] for r in result["results"]] == ["processed", "approval_required"]
        refreshed = session.get(NegotiationSession, session_id)
        assert refreshed is not None
        approval_id = refreshed.pending_approval_id
        assert approval_id is not None
    finally:
        session.close()

    approval_payload = _get_approval_payload(approval_id)
    leaks = _find_forbidden_keys(approval_payload)
    assert leaks == [], f"承認payloadに禁止キーが漏れている: {leaks}"
    assert approval_payload["proposal"]["agreed_share"] == 8000.0
    assert approval_payload["public_context"]["standing_offer"] == 8000.0

    session = next(get_session())
    try:
        resolve_remote_approval(session, approval_id, "approved")
        flush_outbox(session, relay)
    finally:
        session.close()

    accept_envelope = relay.sent[-1]
    assert _envelope_shape(accept_envelope) == {
        "message_type": "ACCEPT",
        "intent": "cost.split",
        "payload": {},
        "delta": {"agreed_share": 8000.0},
    }
    leaks = _find_forbidden_keys(accept_envelope["payload"]) + _find_forbidden_keys(
        accept_envelope["delta"]
    )
    assert leaks == []


# ---------------------------------------------------------------------------
# 新規テスト5: 委任OFFなら、本来なら自動合意できる金額でも承認へエスカレートする。
# ---------------------------------------------------------------------------


def test_cost_split_remote_delegation_off_forces_approval_even_within_budget(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    local_personal_id, local_node_id, peer_agent_id, peer_priv, _clone_id = (
        _setup_local_responder(client, auth_headers, tmp_path, delegation_enabled=False)
    )
    session_id = "remote-cost-split-delegation-off"
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
            total_amount=10000.0,
            proposed_share=3000.0,  # デフォルト設定なら本来は自動ACCEPTされる金額
        )
    ]
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationDecision, NegotiationSession
    from enishi_core.services.remote_negotiation import process_inbox

    session = next(get_session())
    try:
        result = process_inbox(session, relay)
        assert [r["action"] for r in result["results"]] == ["processed", "approval_required"]
        refreshed = session.get(NegotiationSession, session_id)
        assert refreshed is not None
        assert refreshed.status == "waiting_approval"
        decision = session.query(NegotiationDecision).filter(
            NegotiationDecision.session_id == session_id
        ).first()
        assert decision is not None
        assert decision.reason_codes == ["cost_split_negotiation_not_delegated"]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 新規テスト6: 自然言語 → 遠隔 cost.split の通し（F5の成果そのもの）。
# ---------------------------------------------------------------------------


def test_cost_split_natural_language_dispatches_remote_negotiation_to_v2_peer(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """自然言語依頼が `cost.split` と解釈され、能力宣言済みのv2ピアへ遠隔交渉として
    開始される（422 `INTENT_NOT_SUPPORTED_FOR_REMOTE_REQUEST` にも
    409 `PEER_CAPABILITY_MISMATCH` にもならない、F5-bの本来の成功経路）。
    """
    relay = _FakeRelay()
    monkeypatch.setattr("enishi_core.api.routes.get_relay_client", lambda: relay)

    class _StubInterpreter:
        def interpret(self, text: str) -> InterpretedRequest:
            return InterpretedRequest(
                intent="cost.split",
                payload={
                    "title": "飲み会の割り勘",
                    "total_amount": 10000.0,
                    "currency": "JPY",
                    "proposed_share": 3000.0,
                },
            )

    monkeypatch.setattr(
        "enishi_core.services.agent_requests.get_interpreter",
        lambda *args, **kwargs: _StubInterpreter(),
    )

    user_id = _user(client, auth_headers)
    _activate_clone(client, auth_headers, user_id)
    _register_peer(
        client,
        auth_headers,
        agent_id="agt_peer_node",
        capabilities=_V2_COST_SPLIT_CAPABILITIES,
    )

    response = client.post(
        "/v1/agent/requests",
        json={"user_id": user_id, "text": "飲み会の割り勘をお願い"},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["intent"] == "cost.split"
    assert len(relay.sent) == 2
    assert relay.sent[0]["message_type"] == "REQUEST"
    assert relay.sent[0]["payload"]["title"] == "飲み会の割り勘"
    assert relay.sent[0]["payload"]["total_amount"] == 10000.0
    assert relay.sent[0]["payload"]["proposed_share"] == 3000.0
    assert relay.sent[1]["message_type"] == "PROPOSE"
    assert relay.sent[1]["delta"] == {"proposed_share": 3000.0}
    leaks = []
    for env in relay.sent:
        leaks.extend(_find_forbidden_keys(env["payload"]))
        leaks.extend(_find_forbidden_keys(env["delta"]))
    assert leaks == []
