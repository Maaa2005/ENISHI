"""Issue #15: 署名済みメッセージを、名乗っているセッションに束縛する。

署名検証とリプレイ検査は通っても、送信者・宛先・intent・session_version が
セッションの記録と合うかは誰も見ていなかった。そのため信頼済みの別ピアが
session_id と次のsequenceを知っているだけで、他人同士の交渉へ署名付きACCEPTを送り
合意を記録させられた。拒否は他の検証失敗と同じ作法（ack + `envelope_rejected` 監査 +
セッション状態を変えない）に従うことを確認する。
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

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


def _register_trusted_peer(
    client: TestClient,
    headers: dict[str, str],
    tmp_path: Path,
    *,
    name: str,
    personal_agent_id: str,
) -> tuple[str, Any]:
    from enishi_core.security.keys import ensure_node_keypair

    identity, private_key = ensure_node_keypair(tmp_path / name)
    created = client.post(
        "/v1/peers",
        json={
            "agent_id": identity.agent_id,
            "display_name": name,
            "public_key": identity.public_key_b64,
            "personal_agent_id": personal_agent_id,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    trusted = client.post(f"/v1/peers/{identity.agent_id}/trust", headers=headers)
    assert trusted.status_code == 200
    return identity.agent_id, private_key


def _start_with_peer_a(
    client: TestClient, headers: dict[str, str], tmp_path: Path
) -> dict[str, Any]:
    """ローカル利用者がピアAと交渉を始め、別の信頼済みピアBも登録した状態を作る。"""
    from enishi_core.database import get_session
    from enishi_core.services.remote_negotiation import start_remote_negotiation

    user = client.post("/v1/users", json={"display_name": "送信側"}, headers=headers)
    assert user.status_code == 201
    user_id = str(user.json()["id"])
    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "束縛テスト", "provider_type": "mock"},
        headers=headers,
    ).json()
    assert client.post(f"/v1/clones/{clone['id']}/activate", headers=headers).status_code == 200

    peer_a_node, peer_a_key = _register_trusted_peer(
        client, headers, tmp_path, name="peer_a", personal_agent_id="pa_peer_a"
    )
    peer_b_node, peer_b_key = _register_trusted_peer(
        client, headers, tmp_path, name="peer_b", personal_agent_id="pa_peer_b"
    )
    identity = client.get(
        "/v1/agent/identity", params={"user_id": user_id}, headers=headers
    ).json()

    session = next(get_session())
    relay = _FakeRelay()
    try:
        negotiation = start_remote_negotiation(
            session,
            relay,
            user_id=user_id,
            peer_agent_id=peer_a_node,
            topic="束縛テスト",
            duration_minutes=DURATION_MINUTES,
            date_range=DATE_RANGE,
            preferred_time_ranges=PREFERRED_TIME_RANGES,
        )
        session_id = negotiation.id
    finally:
        session.close()

    return {
        "session_id": session_id,
        "local_personal_id": str(identity["personal_agent_id"]),
        "local_node_id": str(identity["node_id"]),
        "peer_a": (peer_a_node, "pa_peer_a", peer_a_key),
        "peer_b": (peer_b_node, "pa_peer_b", peer_b_key),
        "relay": relay,
    }


def _envelope(
    ctx: dict[str, Any],
    peer: tuple[str, str, Any],
    *,
    message_type: str,
    delta: dict[str, Any],
    intent: str = "meeting.schedule",
    session_version: int = 1,
) -> dict[str, Any]:
    from enishi_core.security.envelope import build_envelope

    peer_node, peer_personal, private_key = peer
    return build_envelope(
        sender=peer_personal,
        receiver=ctx["local_personal_id"],
        session_id=ctx["session_id"],
        message_type=message_type,
        intent=intent,
        session_version=session_version,
        sequence=3,
        payload={},
        delta=delta,
        requires_human_approval=False,
        private_key=private_key,
        sender_node_id=peer_node,
        receiver_node_id=ctx["local_node_id"],
    )


def _deliver(ctx: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    from enishi_core.database import get_session
    from enishi_core.services.remote_negotiation import process_inbox

    relay: _FakeRelay = ctx["relay"]
    relay.inbox = [{"delivery_id": envelope["message_id"], "envelope": envelope}]
    session = next(get_session())
    try:
        return process_inbox(session, relay)
    finally:
        session.close()


def _assert_session_untouched(ctx: dict[str, Any]) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import Agreement, NegotiationMessage, NegotiationSession

    session = next(get_session())
    try:
        negotiation = session.get(NegotiationSession, ctx["session_id"])
        assert negotiation is not None
        assert negotiation.status == "open"
        assert negotiation.last_sequence == 2
        assert (
            session.query(Agreement).filter(Agreement.session_id == ctx["session_id"]).count()
            == 0
        )
        assert (
            session.query(NegotiationMessage)
            .filter(NegotiationMessage.session_id == ctx["session_id"])
            .count()
            == 2
        )
    finally:
        session.close()


def test_other_trusted_peer_cannot_accept_into_someone_elses_session(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    ctx = _start_with_peer_a(client, auth_headers, tmp_path)
    proposed = ctx["relay"].sent[1]["delta"]["candidate_slots"]
    intruder = _envelope(
        ctx, ctx["peer_b"], message_type="ACCEPT", delta={"selected_slot": proposed[0]}
    )

    result = _deliver(ctx, intruder)

    assert result["results"] == [
        {
            "message_id": intruder["message_id"],
            "action": "rejected",
            "code": "SESSION_BINDING_MISMATCH",
        }
    ]
    assert intruder["message_id"] in ctx["relay"].acked
    _assert_session_untouched(ctx)

    # 割り込みを拒否した後も、本来の相手からの次のメッセージは通常どおり処理される。
    legit = _envelope(
        ctx, ctx["peer_a"], message_type="COUNTER", delta={"candidate_slots": NON_OVERLAPPING}
    )
    assert [r["action"] for r in _deliver(ctx, legit)["results"]] == ["processed"]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"intent": "cost.split"}, "intent"),
        ({"session_version": 2}, "session_version"),
    ],
)
def test_counterparty_message_must_match_session_terms(
    client: TestClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    overrides: dict[str, Any],
    reason: str,
) -> None:
    ctx = _start_with_peer_a(client, auth_headers, tmp_path)
    envelope = _envelope(
        ctx,
        ctx["peer_a"],
        message_type="COUNTER",
        delta={"candidate_slots": NON_OVERLAPPING},
        **overrides,
    )

    result = _deliver(ctx, envelope)

    assert [r["code"] for r in result["results"]] == ["SESSION_BINDING_MISMATCH"], reason
    _assert_session_untouched(ctx)
