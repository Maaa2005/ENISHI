from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient


class _FakeRelay:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.inbox: list[dict[str, Any]] = []
        self.acked: list[str] = []

    def send(self, envelope: dict[str, Any]) -> None:
        self.sent.append(envelope)

    def fetch(self) -> list[dict[str, Any]]:
        deliveries = list(self.inbox)
        self.inbox = []
        return deliveries

    def ack(self, delivery_id: str) -> None:
        self.acked.append(delivery_id)


class _FailOnceRelay(_FakeRelay):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def send(self, envelope: dict[str, Any]) -> None:
        if not self.failed:
            self.failed = True
            raise RuntimeError("relay unavailable")
        super().send(envelope)


def _user_and_clone(client: TestClient, headers: dict[str, str]) -> tuple[str, str]:
    user = client.post(
        "/v1/users", json={"display_name": "受信者"}, headers=headers
    ).json()
    clone = client.post(
        f"/v1/clones/{user['id']}/ensure",
        json={"purpose": "日程調整", "provider_type": "mock"},
        headers=headers,
    ).json()
    assert client.post(
        f"/v1/clones/{clone['id']}/activate", headers=headers
    ).status_code == 200
    return str(user["id"]), str(clone["id"])


def test_decision_evaluator_is_deterministic_and_reason_ordered(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import CloneAgent
    from enishi_core.services.decision_evaluator import evaluate_meeting_schedule

    _user_id, clone_id = _user_and_clone(client, auth_headers)
    session = next(get_session())
    try:
        clone = session.get(CloneAgent, clone_id)
        assert clone is not None
        clone.confidence_score = 0.4
        clone.policy_profile = {"meeting_schedule": {"auto_accept": False}}
        first = evaluate_meeting_schedule(
            clone=clone,
            delegation_enabled=False,
            common_slot_count=2,
            selected_slot={"start": "2026-07-20T13:00", "end": "2026-07-20T13:30"},
            peer_personal_agent_id="pa_peer",
        )
        second = evaluate_meeting_schedule(
            clone=clone,
            delegation_enabled=False,
            common_slot_count=2,
            selected_slot={"start": "2026-07-20T13:00", "end": "2026-07-20T13:30"},
            peer_personal_agent_id="pa_peer",
        )
    finally:
        session.close()
    assert first == second
    assert first.outcome == "approval_required"
    assert first.reason_codes == [
        "schedule_negotiation_not_delegated",
        "clone_confidence_below_threshold",
        "meeting_auto_accept_disabled",
    ]
    assert set(first.evidence) == {
        "delegation_enabled",
        "clone_confidence",
        "confidence_threshold",
        "meeting_auto_accept",
        "common_slot_count",
        "preferred_time_configured",
        "selected_time_within_preference",
        "selected_time_avoided",
        "relationship_auto_accept",
    }


def test_decision_uses_time_preferences_and_relationship_policy(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import CloneAgent
    from enishi_core.services.decision_evaluator import evaluate_meeting_schedule

    _user_id, clone_id = _user_and_clone(client, auth_headers)
    session = next(get_session())
    try:
        clone = session.get(CloneAgent, clone_id)
        assert clone is not None
        clone.confidence_score = 0.9
        clone.preference_profile = {
            "meeting_schedule": {
                "preferred_time_ranges": [{"start": "09:00", "end": "12:00"}],
                "avoid_time_ranges": [{"start": "13:00", "end": "14:00"}],
            },
            "relationships": {"pa_peer": {"allow_auto_accept": False}},
        }
        decision = evaluate_meeting_schedule(
            clone=clone,
            delegation_enabled=True,
            common_slot_count=1,
            selected_slot={"start": "2026-07-20T13:00", "end": "2026-07-20T13:30"},
            peer_personal_agent_id="pa_peer",
        )
    finally:
        session.close()

    assert decision.outcome == "approval_required"
    assert decision.reason_codes == [
        "meeting_outside_preferred_time",
        "meeting_time_avoided",
        "relationship_requires_approval",
    ]


@pytest.mark.parametrize(
    ("resolution", "expected_message", "expected_status", "select_alternative"),
    [
        ("approve", "ACCEPT", "agreed", False),
        ("approve", "COUNTER", "open", True),
        ("reject", "REJECT", "failed", False),
        ("expire", "REJECT", "failed", False),
    ],
)
def test_remote_low_confidence_waits_for_human_and_responds_once(
    client: TestClient,
    auth_headers: dict[str, str],
    tmp_path: Any,
    monkeypatch: Any,
    resolution: str,
    expected_message: str,
    expected_status: str,
    select_alternative: bool,
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import (
        Agreement,
        NegotiationDecision,
        NegotiationSession,
        PeerAgent,
        RelayOutbox,
    )
    from enishi_core.security.envelope import build_envelope
    from enishi_core.security.keys import ensure_node_keypair
    from enishi_core.services import negotiation as negotiation_service
    from enishi_core.services.remote_negotiation import process_inbox

    _user_id, _clone_id = _user_and_clone(client, auth_headers)
    sender_identity, sender_private = ensure_node_keypair(tmp_path / "sender")
    created = client.post(
        "/v1/peers",
        json={
            "agent_id": sender_identity.agent_id,
            "display_name": "送信者",
            "public_key": sender_identity.public_key_b64,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert client.post(
        f"/v1/peers/{sender_identity.agent_id}/trust", headers=auth_headers
    ).status_code == 200

    session_id = "remote-approval-1"
    request = build_envelope(
        sender=sender_identity.agent_id,
        receiver="receiver",
        session_id=session_id,
        message_type="REQUEST",
        intent="meeting.schedule",
        session_version=1,
        sequence=1,
        payload={
            "topic": "打ち合わせ",
            "duration_minutes": 30,
            "date_range": {"start": "2026-07-20", "end": "2026-07-20"},
            "preferred_time_ranges": [{"start": "13:00", "end": "14:00"}],
        },
        delta={},
        requires_human_approval=False,
        private_key=sender_private,
    )
    propose = build_envelope(
        sender=sender_identity.agent_id,
        receiver="receiver",
        session_id=session_id,
        message_type="PROPOSE",
        intent="meeting.schedule",
        session_version=1,
        sequence=2,
        payload={},
        delta={
            "candidate_slots": [
                {"start": "2026-07-20T13:00", "end": "2026-07-20T13:30"}
            ]
        },
        requires_human_approval=False,
        private_key=sender_private,
    )
    relay = _FakeRelay()
    relay.inbox = [
        {"delivery_id": "d1", "envelope": request},
        {"delivery_id": "d2", "envelope": propose},
    ]
    session = next(get_session())
    try:
        result = process_inbox(session, relay)
        negotiation = session.get(NegotiationSession, session_id)
        assert negotiation is not None
        approval_id = negotiation.pending_approval_id
        assert result["results"][1]["action"] == "approval_required"
        assert negotiation.status == "waiting_approval"
        assert approval_id
        assert relay.sent == []
        assert session.query(NegotiationDecision).one().outcome == "approval_required"
        assert [message.sequence for message in negotiation_service.list_messages(
            session, session_id
        )] == [1, 2]
    finally:
        session.close()

    monkeypatch.setattr("enishi_core.api.routes.get_relay_client", lambda: relay)
    if resolution == "expire":
        from enishi_core.models import Approval
        from enishi_core.models.base import utc_now

        session = next(get_session())
        try:
            approval = session.get(Approval, approval_id)
            assert approval is not None
            approval.expires_at = utc_now() - timedelta(seconds=1)
            session.commit()
        finally:
            session.close()
        assert client.get("/v1/approvals", headers=auth_headers).status_code == 200
        assert client.post("/v1/relay/sync", headers=auth_headers).status_code == 200
    else:
        request_body = None
        if select_alternative:
            approval_body = client.get(
                "/v1/approvals", params={"user_id": _user_id}, headers=auth_headers
            ).json()[0]
            alternatives = approval_body["payload"]["candidate_slots"]
            assert len(alternatives) > 1
            request_body = {"selected_slot": alternatives[1]}
        resolved = client.post(
            f"/v1/approvals/{approval_id}/{resolution}",
            json=request_body,
            headers=auth_headers,
        )
        assert resolved.status_code == 200
    assert [message["message_type"] for message in relay.sent] == [expected_message]
    duplicate = client.post(
        f"/v1/approvals/{approval_id}/approve", headers=auth_headers
    )
    assert duplicate.status_code == 409
    assert [message["message_type"] for message in relay.sent] == [expected_message]
    session = next(get_session())
    try:
        outbox = session.query(RelayOutbox).one()
        assert outbox.status == "sent"
        negotiation = session.get(NegotiationSession, session_id)
        assert negotiation is not None
        assert negotiation.status == expected_status
        agreement = session.query(Agreement).filter_by(session_id=session_id).first()
        if expected_status == "agreed":
            assert agreement is not None
            assert agreement.agreed_payload == {
                "selected_slot": {
                    "start": "2026-07-20T13:00+09:00",
                    "end": "2026-07-20T13:30+09:00",
                }
            }
        else:
            assert agreement is None
        peer = session.get(PeerAgent, sender_identity.agent_id)
        assert peer is not None
    finally:
        session.close()


def test_malformed_signed_payload_is_acked_and_isolated(
    client: TestClient,
    auth_headers: dict[str, str],
    tmp_path: Any,
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import PeerAgent
    from enishi_core.security.envelope import build_envelope
    from enishi_core.security.keys import ensure_node_keypair
    from enishi_core.services.remote_negotiation import process_inbox

    _user_and_clone(client, auth_headers)
    sender_identity, sender_private = ensure_node_keypair(tmp_path / "poison-sender")
    assert client.post(
        "/v1/peers",
        json={
            "agent_id": sender_identity.agent_id,
            "display_name": "不正形式テスト送信者",
            "public_key": sender_identity.public_key_b64,
        },
        headers=auth_headers,
    ).status_code == 201
    assert client.post(
        f"/v1/peers/{sender_identity.agent_id}/trust", headers=auth_headers
    ).status_code == 200

    session_id = "poison-session"
    request = build_envelope(
        sender=sender_identity.agent_id,
        receiver="receiver",
        session_id=session_id,
        message_type="REQUEST",
        intent="meeting.schedule",
        session_version=1,
        sequence=1,
        payload={
            "topic": "不正形式",
            "duration_minutes": "not-a-number",
            "date_range": {"start": "2026-07-20", "end": "2026-07-20"},
            "preferred_time_ranges": [{"start": "13:00", "end": "14:00"}],
        },
        delta={},
        requires_human_approval=False,
        private_key=sender_private,
    )
    propose = build_envelope(
        sender=sender_identity.agent_id,
        receiver="receiver",
        session_id=session_id,
        message_type="PROPOSE",
        intent="meeting.schedule",
        session_version=1,
        sequence=2,
        payload={},
        delta={
            "candidate_slots": [
                {"start": "2026-07-20T13:00", "end": "2026-07-20T13:30"}
            ]
        },
        requires_human_approval=False,
        private_key=sender_private,
    )
    relay = _FakeRelay()
    relay.inbox = [
        {"delivery_id": "poison-request", "envelope": request},
        {"delivery_id": "poison-propose", "envelope": propose},
    ]
    session = next(get_session())
    try:
        peer = session.get(PeerAgent, sender_identity.agent_id)
        assert peer is not None
        result = process_inbox(session, relay)
    finally:
        session.close()

    assert relay.acked == ["poison-request", "poison-propose"]
    assert result["results"][1] == {
        "message_id": propose["message_id"],
        "action": "rejected",
        "code": "MESSAGE_PROCESSING_FAILED",
    }


def test_disabled_delegation_does_not_auto_counter_without_common_slot(
    client: TestClient,
    auth_headers: dict[str, str],
    tmp_path: Any,
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationSession
    from enishi_core.security.envelope import build_envelope
    from enishi_core.security.keys import ensure_node_keypair
    from enishi_core.services.remote_negotiation import process_inbox

    user_id, _clone_id = _user_and_clone(client, auth_headers)
    assert client.put(
        "/v1/policies/delegation",
        json={"user_id": user_id, "rules": {"schedule_negotiation": False}},
        headers=auth_headers,
    ).status_code == 200
    sender_identity, sender_private = ensure_node_keypair(tmp_path / "manual-sender")
    assert client.post(
        "/v1/peers",
        json={
            "agent_id": sender_identity.agent_id,
            "display_name": "送信者",
            "public_key": sender_identity.public_key_b64,
        },
        headers=auth_headers,
    ).status_code == 201
    assert client.post(
        f"/v1/peers/{sender_identity.agent_id}/trust", headers=auth_headers
    ).status_code == 200

    session_id = "manual-counter-session"
    request = build_envelope(
        sender=sender_identity.agent_id,
        receiver="receiver",
        session_id=session_id,
        message_type="REQUEST",
        intent="meeting.schedule",
        session_version=1,
        sequence=1,
        payload={
            "topic": "手動判断",
            "duration_minutes": 30,
            "date_range": {"start": "2026-07-20", "end": "2026-07-20"},
            "preferred_time_ranges": [{"start": "13:00", "end": "14:00"}],
        },
        delta={},
        requires_human_approval=False,
        private_key=sender_private,
    )
    propose = build_envelope(
        sender=sender_identity.agent_id,
        receiver="receiver",
        session_id=session_id,
        message_type="PROPOSE",
        intent="meeting.schedule",
        session_version=1,
        sequence=2,
        payload={},
        delta={
            "candidate_slots": [
                {"start": "2026-07-20T15:00", "end": "2026-07-20T15:30"}
            ]
        },
        requires_human_approval=False,
        private_key=sender_private,
    )
    relay = _FakeRelay()
    relay.inbox = [
        {"delivery_id": "manual-request", "envelope": request},
        {"delivery_id": "manual-propose", "envelope": propose},
    ]
    session = next(get_session())
    try:
        result = process_inbox(session, relay)
        negotiation = session.get(NegotiationSession, session_id)
        assert negotiation is not None
        assert negotiation.status == "waiting_approval"
        assert negotiation.pending_approval_id is not None
    finally:
        session.close()

    assert result["results"][1]["action"] == "approval_required"
    assert relay.sent == []


def test_outbox_retries_the_same_envelope(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationSession, RelayOutbox
    from enishi_core.services.remote_negotiation import flush_outbox

    _user_id, clone_id = _user_and_clone(client, auth_headers)
    session = next(get_session())
    try:
        negotiation = NegotiationSession(
            initiator_clone_id="remote-clone",
            responder_clone_id=clone_id,
            intent="meeting.schedule",
            topic="再送テスト",
        )
        session.add(negotiation)
        session.flush()
        envelope = {"message_id": "fixed-message-id", "message_type": "ACCEPT"}
        outbox = RelayOutbox(
            message_id="fixed-message-id",
            session_id=negotiation.id,
            envelope=envelope,
        )
        session.add(outbox)
        session.commit()

        relay = _FailOnceRelay()
        first = flush_outbox(session, relay)
        assert first == {"sent": 0, "failed": 1, "pending": 1}
        assert outbox.status == "pending"
        assert outbox.attempts == 1

        second = flush_outbox(session, relay)
        assert second == {"sent": 1, "failed": 0, "pending": 0}
        assert outbox.status == "sent"
        assert outbox.attempts == 2
        assert relay.sent == [envelope]
    finally:
        session.close()


def test_outbox_preserves_message_order_after_failure(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationSession, RelayOutbox
    from enishi_core.services.remote_negotiation import flush_outbox

    _user_id, clone_id = _user_and_clone(client, auth_headers)
    session = next(get_session())
    try:
        negotiation = NegotiationSession(
            initiator_clone_id=clone_id,
            responder_clone_id="remote-clone",
            intent="meeting.schedule",
            topic="順序テスト",
        )
        session.add(negotiation)
        session.flush()
        for message_id, sequence in (("request-id", 1), ("propose-id", 2)):
            session.add(
                RelayOutbox(
                    message_id=message_id,
                    session_id=negotiation.id,
                    envelope={"message_id": message_id, "sequence": sequence},
                )
            )
        session.commit()

        relay = _FailOnceRelay()
        first = flush_outbox(session, relay)
        assert first == {"sent": 0, "failed": 1, "pending": 2}
        assert relay.sent == []

        second = flush_outbox(session, relay)
        assert second == {"sent": 2, "failed": 0, "pending": 0}
        assert [item["sequence"] for item in relay.sent] == [1, 2]
    finally:
        session.close()
