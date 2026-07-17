from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
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


def _create_user(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post("/v1/users", json={"display_name": name}, headers=headers)
    assert response.status_code == 201
    return str(response.json()["id"])


def _activate_clone(client: TestClient, headers: dict[str, str], user_id: str) -> str:
    clone_response = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "交渉", "provider_type": "mock"},
        headers=headers,
    )
    assert clone_response.status_code == 200
    clone_id = str(clone_response.json()["id"])
    activated = client.post(f"/v1/clones/{clone_id}/activate", headers=headers)
    assert activated.status_code == 200
    return clone_id


def _register_peer(client: TestClient, headers: dict[str, str], agent_id: str) -> None:
    response = client.post(
        "/v1/peers",
        json={"agent_id": agent_id, "display_name": "相手AI", "public_key": _PUBLIC_KEY},
        headers=headers,
    )
    assert response.status_code == 201
    trusted = client.post(f"/v1/peers/{agent_id}/trust", headers=headers)
    assert trusted.status_code == 200


def _add_memory(
    client: TestClient,
    headers: dict[str, str],
    user_id: str,
    *,
    memory_type: str,
    title: str,
    content: dict[str, Any],
    sensitivity: str = "internal",
) -> None:
    response = client.post(
        "/v1/memories",
        json={
            "user_id": user_id,
            "source_type": "manual",
            "memory_type": memory_type,
            "title": title,
            "content": content,
            "sensitivity": sensitivity,
        },
        headers=headers,
    )
    assert response.status_code == 201


def _task_request(
    client: TestClient,
    headers: dict[str, str],
    initiator_user_id: str,
    responder_user_id: str,
    *,
    estimated_hours: float,
    deadline: str = "2099-01-01",
) -> dict[str, Any]:
    response = client.post(
        "/v1/negotiations",
        json={
            "intent": "task.request",
            "initiator_user_id": initiator_user_id,
            "responder_user_id": responder_user_id,
            "title": "資料作成",
            "description": "提案資料を作る",
            "deadline": deadline,
            "estimated_hours": estimated_hours,
            "conditions": {"format": "slides"},
        },
        headers=headers,
    )
    assert response.status_code == 201
    return dict(response.json())


def test_disclosure_policy_filters_private_context_payload(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    user_id = _create_user(client, auth_headers, "中村")
    clone_id = _activate_clone(client, auth_headers, user_id)
    _register_peer(client, auth_headers, "agt_peer_policy")
    disclosure = client.put(
        "/v1/peers/agt_peer_policy/disclosure",
        json={
            "allowed_memory_types": ["preference"],
            "max_sensitivity": "internal",
            "share_schedule": True,
            "share_skills": False,
            "extra": {},
        },
        headers=auth_headers,
    )
    assert disclosure.status_code == 200
    _add_memory(
        client,
        auth_headers,
        user_id,
        memory_type="preference",
        title="公開可能な好み",
        content={"value": "morning"},
        sensitivity="internal",
    )
    _add_memory(
        client,
        auth_headers,
        user_id,
        memory_type="preference",
        title="privateな好み",
        content={"value": "private-body"},
        sensitivity="private",
    )

    package = client.post(
        "/v1/context-packages",
        json={
            "clone_id": clone_id,
            "task_goal": "相手に渡す文脈",
            "peer_agent_id": "agt_peer_policy",
        },
        headers=auth_headers,
    )
    assert package.status_code == 200
    preferences = package.json()["relevant_preferences"]
    assert "公開可能な好み" in preferences
    assert "privateな好み" not in preferences
    assert "private-body" not in str(package.json())


def test_share_schedule_false_rejects_remote_schedule_query(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from enishi_core.database import get_session
    from enishi_core.errors import EnishiError
    from enishi_core.services.remote_negotiation import start_remote_negotiation

    user_id = _create_user(client, auth_headers, "中村")
    _activate_clone(client, auth_headers, user_id)
    _register_peer(client, auth_headers, "agt_no_schedule")
    response = client.put(
        "/v1/peers/agt_no_schedule/disclosure",
        json={
            "allowed_memory_types": ["schedule"],
            "max_sensitivity": "internal",
            "share_schedule": False,
            "share_skills": False,
            "extra": {},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200

    session = next(get_session())
    try:
        with pytest.raises(EnishiError) as exc:
            start_remote_negotiation(
                session,
                _FakeRelay(),
                user_id=user_id,
                peer_agent_id="agt_no_schedule",
                topic="打ち合わせ",
                duration_minutes=30,
                date_range={"start": "2026-07-13", "end": "2026-07-13"},
                preferred_time_ranges=[{"start": "13:00", "end": "14:00"}],
            )
    finally:
        session.close()
    assert exc.value.code == "DISCLOSURE_POLICY_DENIED"


def test_task_request_auto_accept_creates_agreement(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    initiator = _create_user(client, auth_headers, "中村")
    responder = _create_user(client, auth_headers, "田中")
    _activate_clone(client, auth_headers, initiator)
    _activate_clone(client, auth_headers, responder)

    negotiation = _task_request(client, auth_headers, initiator, responder, estimated_hours=1.5)
    assert negotiation["status"] == "agreed"
    assert negotiation["intent"] == "task.request"

    agreements = client.get(
        "/v1/agreements",
        params={"status": "active", "intent": "task.request"},
        headers=auth_headers,
    )
    assert agreements.status_code == 200
    assert len(agreements.json()) == 1
    assert agreements.json()[0]["session_id"] == negotiation["id"]
    assert agreements.json()[0]["agreed_payload"]["title"] == "資料作成"


def test_task_request_counter_when_within_counter_policy(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    initiator = _create_user(client, auth_headers, "中村")
    responder = _create_user(client, auth_headers, "田中")
    _activate_clone(client, auth_headers, initiator)
    _activate_clone(client, auth_headers, responder)

    negotiation = _task_request(client, auth_headers, initiator, responder, estimated_hours=3.0)
    assert negotiation["status"] == "open"
    assert negotiation["result"]["proposed_task"]["estimated_hours"] == 2.0

    messages = client.get(
        f"/v1/negotiations/{negotiation['id']}/messages", headers=auth_headers
    )
    assert [m["message_type"] for m in messages.json()] == ["REQUEST", "COUNTER"]
    assert messages.json()[-1]["payload"] == {"public_reason": "constraint_violation"}


def test_task_request_threshold_exceeded_escalates_to_human_approval(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    initiator = _create_user(client, auth_headers, "中村")
    responder = _create_user(client, auth_headers, "田中")
    _activate_clone(client, auth_headers, initiator)
    _activate_clone(client, auth_headers, responder)

    negotiation = _task_request(client, auth_headers, initiator, responder, estimated_hours=8.0)
    assert negotiation["status"] == "waiting_approval"
    assert negotiation["pending_approval_id"] is not None

    messages = client.get(
        f"/v1/negotiations/{negotiation['id']}/messages", headers=auth_headers
    )
    assert [m["message_type"] for m in messages.json()] == ["REQUEST", "REQUEST_APPROVAL"]
    assert messages.json()[-1]["requires_human_approval"] is True


def test_negotiation_escalation_approval_accepts_and_creates_agreement(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    initiator = _create_user(client, auth_headers, "中村")
    responder = _create_user(client, auth_headers, "田中")
    _activate_clone(client, auth_headers, initiator)
    _activate_clone(client, auth_headers, responder)
    negotiation = _task_request(client, auth_headers, initiator, responder, estimated_hours=8.0)

    approved = client.post(
        f"/v1/approvals/{negotiation['pending_approval_id']}/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 200
    refreshed = client.get(f"/v1/negotiations/{negotiation['id']}", headers=auth_headers)
    assert refreshed.json()["status"] == "agreed"

    messages = client.get(
        f"/v1/negotiations/{negotiation['id']}/messages", headers=auth_headers
    )
    assert messages.json()[-1]["message_type"] == "ACCEPT"
    assert messages.json()[-1]["requires_human_approval"] is True
    agreements = client.get("/v1/agreements", headers=auth_headers).json()
    assert agreements[0]["session_id"] == negotiation["id"]


def test_negotiation_escalation_rejects(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    initiator = _create_user(client, auth_headers, "中村")
    responder = _create_user(client, auth_headers, "田中")
    _activate_clone(client, auth_headers, initiator)
    _activate_clone(client, auth_headers, responder)
    negotiation = _task_request(client, auth_headers, initiator, responder, estimated_hours=8.0)

    rejected = client.post(
        f"/v1/approvals/{negotiation['pending_approval_id']}/reject",
        headers=auth_headers,
    )
    assert rejected.status_code == 200
    refreshed = client.get(f"/v1/negotiations/{negotiation['id']}", headers=auth_headers)
    assert refreshed.json()["status"] == "failed"
    assert refreshed.json()["result"]["code"] == "APPROVAL_REJECTED"

    messages = client.get(
        f"/v1/negotiations/{negotiation['id']}/messages", headers=auth_headers
    )
    assert messages.json()[-1]["message_type"] == "REJECT"


def test_negotiation_escalation_expiry_rejects_and_cannot_later_accept(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import Approval

    initiator = _create_user(client, auth_headers, "中村")
    responder = _create_user(client, auth_headers, "田中")
    _activate_clone(client, auth_headers, initiator)
    _activate_clone(client, auth_headers, responder)
    negotiation = _task_request(client, auth_headers, initiator, responder, estimated_hours=8.0)
    approval_id = str(negotiation["pending_approval_id"])

    session = next(get_session())
    try:
        approval = session.get(Approval, approval_id)
        assert approval is not None
        approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    finally:
        session.close()

    listed = client.get("/v1/approvals", headers=auth_headers)
    assert listed.status_code == 200
    refreshed = client.get(f"/v1/negotiations/{negotiation['id']}", headers=auth_headers)
    assert refreshed.json()["status"] == "failed"
    assert refreshed.json()["result"]["code"] == "APPROVAL_EXPIRED"

    late = client.post(f"/v1/approvals/{approval_id}/approve", headers=auth_headers)
    assert late.status_code == 409
    assert late.json()["error"]["code"] == "APPROVAL_EXPIRED"


def test_agreement_status_patch_and_audit_payload_omits_body(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import AuditLog
    from sqlalchemy import select

    initiator = _create_user(client, auth_headers, "中村")
    responder = _create_user(client, auth_headers, "田中")
    _activate_clone(client, auth_headers, initiator)
    _activate_clone(client, auth_headers, responder)
    negotiation = _task_request(client, auth_headers, initiator, responder, estimated_hours=1.0)
    agreement = client.get(
        "/v1/agreements",
        params={"status": "active", "intent": "task.request"},
        headers=auth_headers,
    ).json()[0]

    patched = client.patch(
        f"/v1/agreements/{agreement['id']}",
        json={"status": "fulfilled"},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "fulfilled"
    filtered = client.get(
        "/v1/agreements", params={"status": "active"}, headers=auth_headers
    )
    assert filtered.json() == []

    session = next(get_session())
    try:
        events = list(
            session.scalars(
                select(AuditLog).where(AuditLog.event_type == "agreement_created")
            )
        )
    finally:
        session.close()
    assert events
    assert events[0].payload["session_id"] == negotiation["id"]
    assert "資料作成" not in str(events[0].payload)


def test_relay_redelivery_does_not_process_twice(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Any
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import NegotiationMessage, NegotiationSession, PeerAgent
    from enishi_core.security.envelope import build_envelope
    from enishi_core.security.keys import ensure_node_keypair
    from enishi_core.services.remote_negotiation import process_inbox

    user_id = _create_user(client, auth_headers, "受信者")
    _activate_clone(client, auth_headers, user_id)
    sender_identity, sender_private_key = ensure_node_keypair(tmp_path / "sender")
    _register_peer(client, auth_headers, sender_identity.agent_id)

    session = next(get_session())
    try:
        peer = session.get(PeerAgent, sender_identity.agent_id)
        assert peer is not None
        peer.public_key = sender_identity.public_key_b64
        session.commit()
    finally:
        session.close()

    envelope = build_envelope(
        sender=sender_identity.agent_id,
        receiver="receiver",
        session_id="remote-session-1",
        message_type="REQUEST",
        intent="meeting.schedule",
        session_version=1,
        sequence=1,
        payload={
            "topic": "打ち合わせ",
            "duration_minutes": 30,
            "date_range": {"start": "2026-07-13", "end": "2026-07-13"},
            "preferred_time_ranges": [{"start": "13:00", "end": "14:00"}],
        },
        delta={},
        requires_human_approval=False,
        private_key=sender_private_key,
    )
    relay = _FakeRelay()
    relay.inbox = [
        {"delivery_id": "d1", "envelope": envelope},
        {"delivery_id": "d2", "envelope": dict(envelope)},
    ]

    session = next(get_session())
    try:
        result = process_inbox(session, relay)
        assert result["processed"] == 2
        assert result["results"][1]["action"] == "duplicate"
        assert relay.acked == ["d1", "d2"]
        assert len(session.query(NegotiationSession).all()) == 1
        assert len(session.query(NegotiationMessage).all()) == 1
    finally:
        session.close()


def test_restricted_schedule_body_reason_and_raw_range_not_sent_or_logged(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import AuditLog
    from enishi_core.services.remote_negotiation import start_remote_negotiation
    from sqlalchemy import select

    marker = "restricted-secret-body"
    user_id = _create_user(client, auth_headers, "中村")
    _activate_clone(client, auth_headers, user_id)
    _register_peer(client, auth_headers, "agt_restricted_peer")
    _add_memory(
        client,
        auth_headers,
        user_id,
        memory_type="schedule",
        title="秘匿予定",
        content={
            "busy": [{"start": "2026-07-13T13:00", "end": "2026-07-13T13:30"}],
            "reason": marker,
            "raw_range": "2026-07-13T13:00/2026-07-13T13:30",
        },
        sensitivity="restricted",
    )

    session = next(get_session())
    relay = _FakeRelay()
    try:
        start_remote_negotiation(
            session,
            relay,
            user_id=user_id,
            peer_agent_id="agt_restricted_peer",
            topic="打ち合わせ",
            duration_minutes=30,
            date_range={"start": "2026-07-13", "end": "2026-07-13"},
            preferred_time_ranges=[{"start": "13:00", "end": "14:00"}],
        )
        audit_payloads = list(session.scalars(select(AuditLog.payload)))
    finally:
        session.close()

    assert marker not in str(relay.sent)
    assert "raw_range" not in str(relay.sent)
    assert marker not in str(audit_payloads)
    assert "raw_range" not in str(audit_payloads)


def test_disclosure_policy_affects_remote_candidate_calculation_and_payload(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from enishi_core.database import get_session
    from enishi_core.services.remote_negotiation import start_remote_negotiation

    user_id = _create_user(client, auth_headers, "中村")
    _activate_clone(client, auth_headers, user_id)
    _register_peer(client, auth_headers, "agt_schedule_peer")
    _add_memory(
        client,
        auth_headers,
        user_id,
        memory_type="schedule",
        title="公開可能busy",
        content={"busy": [{"start": "2026-07-13T13:00", "end": "2026-07-13T13:30"}]},
        sensitivity="internal",
    )

    response = client.put(
        "/v1/peers/agt_schedule_peer/disclosure",
        json={
            "allowed_memory_types": [],
            "max_sensitivity": "internal",
            "share_schedule": True,
            "share_skills": False,
            "extra": {},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    session = next(get_session())
    relay_without_schedule = _FakeRelay()
    try:
        start_remote_negotiation(
            session,
            relay_without_schedule,
            user_id=user_id,
            peer_agent_id="agt_schedule_peer",
            topic="打ち合わせ",
            duration_minutes=30,
            date_range={"start": "2026-07-13", "end": "2026-07-13"},
            preferred_time_ranges=[{"start": "13:00", "end": "14:00"}],
        )
    finally:
        session.close()
    first_candidates = relay_without_schedule.sent[1]["delta"]["candidate_slots"]
    assert first_candidates[0]["start"] == "2026-07-13T13:00+09:00"

    response = client.put(
        "/v1/peers/agt_schedule_peer/disclosure",
        json={
            "allowed_memory_types": ["schedule"],
            "max_sensitivity": "internal",
            "share_schedule": True,
            "share_skills": False,
            "extra": {},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    session = next(get_session())
    relay_with_schedule = _FakeRelay()
    try:
        start_remote_negotiation(
            session,
            relay_with_schedule,
            user_id=user_id,
            peer_agent_id="agt_schedule_peer",
            topic="打ち合わせ",
            duration_minutes=30,
            date_range={"start": "2026-07-13", "end": "2026-07-13"},
            preferred_time_ranges=[{"start": "13:00", "end": "14:00"}],
        )
    finally:
        session.close()
    second_candidates = relay_with_schedule.sent[1]["delta"]["candidate_slots"]
    assert second_candidates[0]["start"] == "2026-07-13T13:30+09:00"
    assert "公開可能busy" not in str(relay_with_schedule.sent)


def test_remote_negotiation_rejects_incompatible_v2_peer(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from enishi_core.database import get_session
    from enishi_core.errors import EnishiError
    from enishi_core.services.remote_negotiation import start_remote_negotiation

    user_id = _create_user(client, auth_headers, "中村")
    _activate_clone(client, auth_headers, user_id)
    created = client.post(
        "/v1/peers",
        json={
            "agent_id": "agt_incompatible",
            "display_name": "非対応AI",
            "public_key": _PUBLIC_KEY,
            "capabilities": {
                "timezone": "Asia/Tokyo",
                "supported_intents": ["task.request"],
                "protocol_versions": ["aun/0.1"],
            },
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert client.post(
        "/v1/peers/agt_incompatible/trust", headers=auth_headers
    ).status_code == 200

    session = next(get_session())
    try:
        with pytest.raises(EnishiError) as exc:
            start_remote_negotiation(
                session,
                _FakeRelay(),
                user_id=user_id,
                peer_agent_id="agt_incompatible",
                topic="打ち合わせ",
                duration_minutes=30,
                date_range={"start": "2026-07-13", "end": "2026-07-13"},
                preferred_time_ranges=[{"start": "13:00", "end": "14:00"}],
            )
        assert exc.value.code == "PEER_CAPABILITY_MISMATCH"
    finally:
        session.close()
