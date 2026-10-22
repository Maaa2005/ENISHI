"""Phase G2: 受信REQUESTのガード（Codexレビュー指摘: 受信側が素通りだった穴を塞ぐ）。

送信側（`start_remote_negotiation`）は `get_domain()` / `domain.supports_remote` /
`domain.validate_request()` / `_require_peer_capability()` を通してからワイヤへ送るが、
受信側（`_handle_envelope` の REQUEST 分岐）はこれまでこれらを一切確認せず
`NegotiationSession` を永続化していた。ここでは受信側にも同等のガードが効いていることを
確認する。不正REQUESTの拒否は既存の作法（`process_inbox` がack + `envelope_rejected` 監査 +
セッション非永続化）に合わせる（`test_agent_decisions.py::
test_malformed_signed_payload_is_acked_and_isolated` と同じ形）。

能力宣言の整合チェックだけは送信側と非対称にしてある
（`remote_negotiation._require_peer_capability_for_receive` を参照）。送信側は
「相手が宣言していない intent を送らない」という**相手を守る**判定だが、受信側で
同じ判定をしても自分は何も守られない（`supports_remote` が真＝実装済みで処理できる）。
空の `capabilities` は「相手の能力が meeting.schedule 限定」ではなく「こちらがまだ
相手のv2名刺を持っていない」というだけの意味であり、それを制限と解釈すると
名刺未交換・未更新なだけの正当なv1ピアと相互運用できなくなる（このブランチの
後方互換方針に反する）。よって受信側では「名刺が**非空**でその intent を含まない」
場合のみ拒否する。
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_PUBLIC_KEY = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="


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


def _user(client: TestClient, headers: dict[str, str], name: str = "受信側") -> str:
    response = client.post("/v1/users", json={"display_name": name}, headers=headers)
    assert response.status_code == 201
    return str(response.json()["id"])


def _activate_clone(client: TestClient, headers: dict[str, str], user_id: str) -> str:
    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "受信テスト", "provider_type": "mock"},
        headers=headers,
    ).json()
    assert client.post(f"/v1/clones/{clone['id']}/activate", headers=headers).status_code == 200
    return str(clone["id"])


def _local_ids(client: TestClient, headers: dict[str, str], user_id: str) -> tuple[str, str]:
    response = client.get(
        "/v1/agent/identity", params={"user_id": user_id}, headers=headers
    )
    assert response.status_code == 200, response.text
    identity = response.json()
    return str(identity["personal_agent_id"]), str(identity["node_id"])


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


def _setup_responder(
    client: TestClient,
    headers: dict[str, str],
    tmp_path: Path,
    *,
    capabilities: dict[str, Any] | None = None,
) -> tuple[str, str, str, Any]:
    """相手ノード（peer）と、応答側になるローカルユーザーをセットアップする。

    戻り値: (local_personal_id, local_node_id, peer_agent_id, peer_private_key)
    """
    from enishi_core.security.keys import ensure_node_keypair

    peer_identity, peer_private_key = ensure_node_keypair(tmp_path / "peer")
    user_id = _user(client, headers)
    _activate_clone(client, headers, user_id)
    _register_peer(
        client,
        headers,
        agent_id=peer_identity.agent_id,
        personal_agent_id="pa_peer",
        public_key=peer_identity.public_key_b64,
        capabilities=capabilities,
    )
    local_personal_id, local_node_id = _local_ids(client, headers, user_id)
    return local_personal_id, local_node_id, peer_identity.agent_id, peer_private_key


def _build_request_envelope(
    *,
    session_id: str,
    peer_personal_id: str,
    local_personal_id: str,
    peer_node_id: str,
    local_node_id: str,
    private_key: Any,
    intent: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from enishi_core.security.envelope import build_envelope

    return build_envelope(
        sender=peer_personal_id,
        receiver=local_personal_id,
        session_id=session_id,
        message_type="REQUEST",
        intent=intent,
        session_version=1,
        sequence=1,
        payload=payload,
        delta={},
        requires_human_approval=False,
        private_key=private_key,
        sender_node_id=peer_node_id,
        receiver_node_id=local_node_id,
    )


def _process(relay: _FakeRelay) -> dict[str, Any]:
    from enishi_core.database import get_session
    from enishi_core.services.remote_negotiation import process_inbox

    session = next(get_session())
    try:
        return process_inbox(session, relay)
    finally:
        session.close()


def _negotiation_exists(session_id: str) -> bool:
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationSession

    session = next(get_session())
    try:
        return session.get(NegotiationSession, session_id) is not None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 新規テスト1: 名刺で meeting.schedule しか宣言していないv2ピアが cost.split の
# REQUESTを送ってくる → 受理されず、セッションが永続化されない。
# ---------------------------------------------------------------------------


def test_request_rejected_when_intent_not_in_peer_declared_capabilities(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    local_personal_id, local_node_id, peer_agent_id, peer_priv = _setup_responder(
        client,
        auth_headers,
        tmp_path,
        capabilities={
            "timezone": "UTC",
            "supported_intents": ["meeting.schedule"],
            "protocol_versions": ["aun/0.2"],
        },
    )
    session_id = "guard-capability-mismatch"
    request = _build_request_envelope(
        session_id=session_id,
        peer_personal_id="pa_peer",
        local_personal_id=local_personal_id,
        peer_node_id=peer_agent_id,
        local_node_id=local_node_id,
        private_key=peer_priv,
        intent="cost.split",
        payload={
            "title": "不整合テスト",
            "total_amount": 10000.0,
            "currency": "JPY",
            "proposed_share": 3000.0,
        },
    )
    relay = _FakeRelay()
    relay.inbox = [{"delivery_id": "d1", "envelope": request}]

    result = _process(relay)

    assert relay.acked == ["d1"]
    assert result["results"] == [
        {
            "message_id": request["message_id"],
            "action": "rejected",
            "code": "PEER_CAPABILITY_MISMATCH",
        }
    ]
    assert _negotiation_exists(session_id) is False


# ---------------------------------------------------------------------------
# 新規テスト2: 遠隔ドライバ未実装のドメイン（task.request, supports_remote=False）の
# REQUESTが送られてくる → 受理されない。
# ---------------------------------------------------------------------------


def test_request_rejected_when_domain_does_not_support_remote(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    local_personal_id, local_node_id, peer_agent_id, peer_priv = _setup_responder(
        client, auth_headers, tmp_path
    )
    session_id = "guard-unsupported-remote-domain"
    request = _build_request_envelope(
        session_id=session_id,
        peer_personal_id="pa_peer",
        local_personal_id=local_personal_id,
        peer_node_id=peer_agent_id,
        local_node_id=local_node_id,
        private_key=peer_priv,
        intent="task.request",
        payload={"title": "遠隔未対応タスク"},
    )
    relay = _FakeRelay()
    relay.inbox = [{"delivery_id": "d1", "envelope": request}]

    result = _process(relay)

    assert relay.acked == ["d1"]
    assert result["results"] == [
        {
            "message_id": request["message_id"],
            "action": "rejected",
            "code": "INTENT_NOT_SUPPORTED_FOR_REMOTE_REQUEST",
        }
    ]
    assert _negotiation_exists(session_id) is False


# ---------------------------------------------------------------------------
# 新規テスト3: 未登録intentのREQUEST → 受理されない。
# ---------------------------------------------------------------------------


def test_request_rejected_for_unknown_intent(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    local_personal_id, local_node_id, peer_agent_id, peer_priv = _setup_responder(
        client, auth_headers, tmp_path
    )
    session_id = "guard-unknown-intent"
    request = _build_request_envelope(
        session_id=session_id,
        peer_personal_id="pa_peer",
        local_personal_id=local_personal_id,
        peer_node_id=peer_agent_id,
        local_node_id=local_node_id,
        private_key=peer_priv,
        intent="not.a.real.intent",
        payload={},
    )
    relay = _FakeRelay()
    relay.inbox = [{"delivery_id": "d1", "envelope": request}]

    result = _process(relay)

    assert relay.acked == ["d1"]
    assert result["results"] == [
        {"message_id": request["message_id"], "action": "rejected", "code": "UNKNOWN_INTENT"}
    ]
    assert _negotiation_exists(session_id) is False


# ---------------------------------------------------------------------------
# 新規テスト4: 壊れたpayload（必須フィールド欠落）のREQUEST → 永続化前に弾かれる。
# ---------------------------------------------------------------------------


def test_request_rejected_for_malformed_payload_before_persisting(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    local_personal_id, local_node_id, peer_agent_id, peer_priv = _setup_responder(
        client,
        auth_headers,
        tmp_path,
        capabilities={
            "timezone": "UTC",
            "supported_intents": ["cost.split"],
            "protocol_versions": ["aun/0.2"],
        },
    )
    session_id = "guard-malformed-payload"
    request = _build_request_envelope(
        session_id=session_id,
        peer_personal_id="pa_peer",
        local_personal_id=local_personal_id,
        peer_node_id=peer_agent_id,
        local_node_id=local_node_id,
        private_key=peer_priv,
        intent="cost.split",
        # total_amount（必須）が欠落
        payload={"title": "壊れたpayload", "proposed_share": 3000.0},
    )
    relay = _FakeRelay()
    relay.inbox = [{"delivery_id": "d1", "envelope": request}]

    result = _process(relay)

    assert relay.acked == ["d1"]
    assert result["results"] == [
        {
            "message_id": request["message_id"],
            "action": "rejected",
            "code": "INVALID_NEGOTIATION_PAYLOAD",
        }
    ]
    assert _negotiation_exists(session_id) is False


# ---------------------------------------------------------------------------
# 新規テスト5（後方互換）: v1ピア（capabilitiesが空）からのmeeting.scheduleは
# 従来どおり受理され、応答が返る。
# ---------------------------------------------------------------------------


def test_v1_peer_without_capabilities_can_still_send_meeting_schedule(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    local_personal_id, local_node_id, peer_agent_id, peer_priv = _setup_responder(
        client, auth_headers, tmp_path
    )
    session_id = "guard-v1-backward-compat"
    request = _build_request_envelope(
        session_id=session_id,
        peer_personal_id="pa_peer",
        local_personal_id=local_personal_id,
        peer_node_id=peer_agent_id,
        local_node_id=local_node_id,
        private_key=peer_priv,
        intent="meeting.schedule",
        payload={
            "topic": "v1互換テスト",
            "duration_minutes": 30,
            "date_range": {"start": "2026-08-03", "end": "2026-08-03"},
            "preferred_time_ranges": [{"start": "13:00", "end": "15:00"}],
        },
    )
    relay = _FakeRelay()
    relay.inbox = [{"delivery_id": "d1", "envelope": request}]

    result = _process(relay)

    assert relay.acked == ["d1"]
    assert result["results"] == [{"message_id": request["message_id"], "action": "processed"}]
    assert _negotiation_exists(session_id) is True


# ---------------------------------------------------------------------------
# 新規テスト6（選択Bの核心）: capabilitiesが空のv1ピアから cost.split のREQUESTが
# 来ても受理される。空＝「相手の能力がmeeting.schedule限定」ではなく「こちらが
# まだ相手のv2名刺を持っていない」というだけの意味であり、制限として扱わない。
# ---------------------------------------------------------------------------


def test_v1_peer_without_capabilities_can_send_cost_split(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    local_personal_id, local_node_id, peer_agent_id, peer_priv = _setup_responder(
        client, auth_headers, tmp_path
    )
    session_id = "guard-v1-cost-split-accepted"
    request = _build_request_envelope(
        session_id=session_id,
        peer_personal_id="pa_peer",
        local_personal_id=local_personal_id,
        peer_node_id=peer_agent_id,
        local_node_id=local_node_id,
        private_key=peer_priv,
        intent="cost.split",
        payload={
            "title": "v1ピアからの割り勘依頼",
            "total_amount": 10000.0,
            "currency": "JPY",
            "proposed_share": 3000.0,
        },
    )
    relay = _FakeRelay()
    relay.inbox = [{"delivery_id": "d1", "envelope": request}]

    result = _process(relay)

    assert relay.acked == ["d1"]
    assert result["results"] == [{"message_id": request["message_id"], "action": "processed"}]
    assert _negotiation_exists(session_id) is True


# ---------------------------------------------------------------------------
# 受信箱の定期ポーリング: 空振りは監査ログに残さず、処理した時だけ件数を残す。
# ---------------------------------------------------------------------------


def _inbox_processed_counts() -> list[Any]:
    from enishi_core.database import get_session
    from enishi_core.models.audit import AuditLog

    session = next(get_session())
    try:
        rows = session.query(AuditLog).filter(AuditLog.event_type == "inbox_processed").all()
        return [row.payload.get("processed") for row in rows]
    finally:
        session.close()


def test_empty_inbox_poll_does_not_write_audit_event(client: TestClient) -> None:
    relay = _FakeRelay()

    for _ in range(3):
        assert _process(relay) == {"processed": 0, "results": []}

    assert _inbox_processed_counts() == []


def test_inbox_poll_with_deliveries_writes_one_audit_event(client: TestClient) -> None:
    relay = _FakeRelay()
    relay.inbox = [{"delivery_id": "broken", "envelope": "not-an-object"}]

    result = _process(relay)

    assert result["processed"] == 1
    assert relay.acked == ["broken"]
    assert _inbox_processed_counts() == [1]
