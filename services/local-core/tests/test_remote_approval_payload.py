"""Phase F2: 承認payloadの脱ドメイン化（後方互換つき）のテスト
（.tmp/phase-f2-f4-spec.md 新規テスト1〜3）。

`tests/test_remote_domains.py`（ゴールデン）とはシナリオセットアップの形が似ているが、
ゴールデンファイル自体は1行も変更してはいけないため、必要な最小限のヘルパーをここへ
複製する（依存を作らない）。
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_PUBLIC_KEY = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="

DATE_RANGE = {"start": "2026-08-03", "end": "2026-08-03"}
PREFERRED_TIME_RANGES = [{"start": "13:00", "end": "15:00"}]
DURATION_MINUTES = 30

# cost.split の私的パラメータ（domains/README.md, tests/test_cost_split.py と同じ集合）。
# meeting.schedule の承認payloadにこれらが混入しないことを再帰走査で確認する（新規テスト3）。
_FORBIDDEN_KEYS = {
    "reservation_ratio",
    "preferred_ratio",
    "concession_ratio",
    "max_auto_accept_amount",
    "max_negotiable_amount",
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


def _assert_no_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            assert key not in _FORBIDDEN_KEYS, f"forbidden key leaked: {key}"
            _assert_no_forbidden_keys(nested)
    elif isinstance(value, list):
        for item in value:
            _assert_no_forbidden_keys(item)


def _user(client: TestClient, headers: dict[str, str], name: str = "応答側") -> str:
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


def _setup_pending_approval(
    client: TestClient, headers: dict[str, str], tmp_path: Path
) -> tuple[str, str, list[dict[str, str]]]:
    """相手からのREQUEST/PROPOSEを受信し、委任OFFでapproval_requiredな承認を1件作る。"""
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationSession
    from enishi_core.services.remote_negotiation import process_inbox

    peer_identity, peer_priv = _make_peer_identity(tmp_path)
    user_id = _user(client, headers)
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
    session_id = "remote-approval-payload-test"
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
                    "topic": "承認payloadテスト",
                    "duration_minutes": DURATION_MINUTES,
                    "date_range": DATE_RANGE,
                    "preferred_time_ranges": PREFERRED_TIME_RANGES,
                    "timezone": "Asia/Tokyo",
                },
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
    finally:
        session.close()
    return session_id, approval_id, expected_candidates


def test_legacy_approval_payload_resolves_via_selected_slot_fallback(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """新規テスト1: `proposal`/`public_context` を持たない旧形式の承認レコードでも、
    `selected_slot`/`candidate_slots` へのフォールバックで正しく解決できる。
    """
    from enishi_core.database import get_session
    from enishi_core.models import Approval, NegotiationSession, NegotiationStatus
    from enishi_core.services.remote_negotiation import resolve_remote_approval

    _session_id, approval_id, expected_candidates = _setup_pending_approval(
        client, auth_headers, tmp_path
    )

    session = next(get_session())
    try:
        approval = session.get(Approval, approval_id)
        assert approval is not None
        # 「この変更以前に作られた承認レコード」を再現する: proposal/public_context を持たず、
        # selected_slot/candidate_slots だけを持つ形へ書き換える。
        legacy_payload = dict(approval.payload)
        legacy_payload.pop("proposal", None)
        legacy_payload.pop("public_context", None)
        approval.payload = legacy_payload
        session.add(approval)
        session.commit()

        resolved = resolve_remote_approval(session, approval_id, "approved")
        session.commit()

        assert resolved.status == "approved"
        negotiation = session.get(NegotiationSession, _session_id)
        assert negotiation is not None
        assert negotiation.status == NegotiationStatus.AGREED.value
        assert negotiation.result["selected_slot"] == expected_candidates[0]
    finally:
        session.close()


def test_meeting_approval_payload_adds_generic_keys_and_keeps_legacy_keys(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """新規テスト2: meeting の承認payloadに `proposal`/`public_context` が追加され、
    かつ `selected_slot`/`candidate_slots` も従来どおり存在する（書き側の後方互換）。
    """
    from enishi_core.database import get_session
    from enishi_core.models import Approval

    _session_id, approval_id, expected_candidates = _setup_pending_approval(
        client, auth_headers, tmp_path
    )

    session = next(get_session())
    try:
        approval = session.get(Approval, approval_id)
        assert approval is not None
        payload = approval.payload

        assert payload["selected_slot"] == expected_candidates[0]
        assert payload["candidate_slots"] == expected_candidates
        assert payload["proposal"] == {"selected_slot": expected_candidates[0]}
        assert payload["public_context"] == {"candidate_slots": expected_candidates}
    finally:
        session.close()


def test_approval_payload_public_context_has_no_private_parameters(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """新規テスト3: 承認payload全体を再帰走査し、留保価格・効用パラメータ・記憶の生データに
    相当するキー（cost.split の私的パラメータ集合）が漏れていないことを確認する。
    """
    from enishi_core.database import get_session
    from enishi_core.models import Approval

    _session_id, approval_id, _expected_candidates = _setup_pending_approval(
        client, auth_headers, tmp_path
    )

    session = next(get_session())
    try:
        approval = session.get(Approval, approval_id)
        assert approval is not None
        _assert_no_forbidden_keys(approval.payload)
        _assert_no_forbidden_keys(approval.payload.get("public_context"))
    finally:
        session.close()
