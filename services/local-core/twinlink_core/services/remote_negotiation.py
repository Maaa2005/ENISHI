"""Relay経由の別所有者ノード間交渉（twinlink.md §25 v2, §26, §35 Phase 6）。

送信側は署名済みエンベロープをRelayへ送り、受信側は署名・信頼ピア・
リプレイ・状態機械を検証してから日程計算する。busyの本文・予定名・
除外理由は送らない（§17 v2）。監査ログにも本文を残さない。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from twinlink_core.config import get_settings
from twinlink_core.errors import TwinLinkError
from twinlink_core.models import (
    Agreement,
    CloneAgent,
    CloneStatus,
    NegotiationMessage,
    NegotiationSession,
    NegotiationStatus,
    PeerAgent,
    PeerStatus,
)
from twinlink_core.security.envelope import build_envelope, verify_envelope
from twinlink_core.security.keys import ensure_node_keypair
from twinlink_core.security.replay import check_and_record
from twinlink_core.services import protocol_state
from twinlink_core.services.audit import log_event
from twinlink_core.services.memories import exportable_memories
from twinlink_core.services.peers import filter_memories_for_peer, get_disclosure_policy
from twinlink_core.services.relay_client import RelayTransport
from twinlink_core.services.scheduling import (
    Slot,
    candidate_slots,
    collect_busy,
    intersect_slots,
)

INTENT = "meeting.schedule"
_OFFER_SIZE = 5


def _require_trusted_peer(session_db: Session, agent_id: str) -> PeerAgent:
    peer = session_db.get(PeerAgent, agent_id)
    if peer is None or peer.status != PeerStatus.TRUSTED.value:
        raise TwinLinkError(
            code="PEER_NOT_TRUSTED",
            message="信頼済みでないピアとは交渉できません。",
            status_code=403,
            details={"agent_id": agent_id},
        )
    return peer


def _find_active_clone(session_db: Session, user_id: str | None = None) -> CloneAgent:
    query = select(CloneAgent).where(CloneAgent.status == CloneStatus.ACTIVE.value)
    if user_id is not None:
        query = query.where(CloneAgent.user_id == user_id)
    clone = session_db.scalars(query.order_by(CloneAgent.created_at.desc())).first()
    if clone is None:
        raise TwinLinkError(
            code="CLONE_REVIEW_REQUIRED",
            message="有効化済みのクローンがありません。",
            status_code=409,
            details={"user_id": user_id or ""},
        )
    return clone


def _own_candidates(
    session_db: Session, user_id: str, request_payload: dict[str, Any], peer_agent_id: str
) -> list[Slot]:
    policy = get_disclosure_policy(session_db, peer_agent_id)
    if not policy.share_schedule:
        raise TwinLinkError(
            code="DISCLOSURE_POLICY_DENIED",
            message="このピアには日程候補を公開しません。",
            status_code=403,
            details={"peer_agent_id": peer_agent_id},
        )
    memories = filter_memories_for_peer(exportable_memories(session_db, user_id), policy)
    busy = collect_busy(memories)
    return candidate_slots(
        dict(request_payload["date_range"]),
        list(request_payload["preferred_time_ranges"]),
        int(request_payload["duration_minutes"]),
        busy,
    )


def _save_message(
    session_db: Session, session_id: str, envelope: dict[str, Any]
) -> NegotiationMessage:
    message = NegotiationMessage(
        session_id=session_id,
        sequence=int(envelope["sequence"]),
        sender_agent_id=str(envelope["sender_agent_id"]),
        receiver_agent_id=str(envelope["receiver_agent_id"]),
        message_type=str(envelope["message_type"]),
        intent=str(envelope["intent"]),
        payload=dict(envelope.get("payload", {})),
        delta=dict(envelope.get("delta", {})),
        requires_human_approval=bool(envelope.get("requires_human_approval", False)),
    )
    session_db.add(message)
    return message


def start_remote_negotiation(
    session_db: Session,
    relay: RelayTransport,
    user_id: str,
    peer_agent_id: str,
    topic: str,
    duration_minutes: int,
    date_range: dict[str, str],
    preferred_time_ranges: list[dict[str, str]],
) -> NegotiationSession:
    """Relay経由で相手ノードへREQUESTとPROPOSEを送る（送信側）。"""
    _require_trusted_peer(session_db, peer_agent_id)
    clone = _find_active_clone(session_db, user_id)
    identity, private_key = ensure_node_keypair(get_settings().data_dir)

    request_payload: dict[str, Any] = {
        "intent": INTENT,
        "topic": topic,
        "duration_minutes": duration_minutes,
        "date_range": date_range,
        "preferred_time_ranges": preferred_time_ranges,
    }
    candidates = _own_candidates(session_db, user_id, request_payload, peer_agent_id)[
        :_OFFER_SIZE
    ]

    negotiation = NegotiationSession(
        initiator_clone_id=clone.id,
        responder_clone_id=peer_agent_id,
        intent=INTENT,
        topic=topic,
        remote_peer_agent_id=peer_agent_id,
        last_sequence=2,
    )
    session_db.add(negotiation)
    session_db.flush()

    # busyの本文・予定名・除外理由は送らない（§17 v2）。構造化リクエストと候補のみ
    request_env = build_envelope(
        sender=identity.agent_id,
        receiver=peer_agent_id,
        session_id=negotiation.id,
        message_type="REQUEST",
        intent=INTENT,
        session_version=negotiation.session_version,
        sequence=1,
        payload=request_payload,
        delta={},
        requires_human_approval=False,
        private_key=private_key,
    )
    propose_env = build_envelope(
        sender=identity.agent_id,
        receiver=peer_agent_id,
        session_id=negotiation.id,
        message_type="PROPOSE",
        intent=INTENT,
        session_version=negotiation.session_version,
        sequence=2,
        payload={},
        delta={"candidate_slots": candidates},
        requires_human_approval=False,
        private_key=private_key,
    )
    relay.send(request_env)
    relay.send(propose_env)

    _save_message(session_db, negotiation.id, request_env)
    _save_message(session_db, negotiation.id, propose_env)
    session_db.commit()
    session_db.refresh(negotiation)

    log_event(
        session_db,
        event_type="remote_negotiation_started",
        payload={"session_id": negotiation.id, "peer_agent_id": peer_agent_id},
    )
    return negotiation


def _last_message(session_db: Session, session_id: str) -> NegotiationMessage | None:
    return session_db.scalars(
        select(NegotiationMessage)
        .where(NegotiationMessage.session_id == session_id)
        .order_by(NegotiationMessage.sequence.desc())
    ).first()


def _request_payload(session_db: Session, session_id: str) -> dict[str, Any]:
    request = session_db.scalars(
        select(NegotiationMessage).where(
            NegotiationMessage.session_id == session_id,
            NegotiationMessage.message_type == "REQUEST",
        )
    ).first()
    if request is None:
        raise TwinLinkError(
            code="INVALID_STATE_TRANSITION",
            message="REQUESTが記録されていないセッションです。",
            status_code=409,
            details={"session_id": session_id},
        )
    return request.payload


def _counter_rounds(session_db: Session, session_id: str) -> int:
    messages = session_db.scalars(
        select(NegotiationMessage).where(
            NegotiationMessage.session_id == session_id,
            NegotiationMessage.message_type == "COUNTER",
        )
    ).all()
    return len(messages)


def _send_reply(
    session_db: Session,
    relay: RelayTransport,
    negotiation: NegotiationSession,
    receiver: str,
    message_type: str,
    sequence: int,
    delta: dict[str, Any],
) -> None:
    identity, private_key = ensure_node_keypair(get_settings().data_dir)
    envelope = build_envelope(
        sender=identity.agent_id,
        receiver=receiver,
        session_id=negotiation.id,
        message_type=message_type,
        intent=INTENT,
        session_version=negotiation.session_version,
        sequence=sequence,
        payload={},
        delta=delta,
        requires_human_approval=False,
        private_key=private_key,
    )
    relay.send(envelope)
    _save_message(session_db, negotiation.id, envelope)
    negotiation.last_sequence = sequence


def _create_remote_agreement(
    session_db: Session,
    negotiation: NegotiationSession,
    agreed_payload: dict[str, Any],
) -> Agreement:
    """リモートACCEPT終端を合意として保存する（twinlink.md 方針修正 §4）。"""
    existing = session_db.scalars(
        select(Agreement).where(Agreement.session_id == negotiation.id)
    ).first()
    if existing is not None:
        return existing
    agreement = Agreement(
        session_id=negotiation.id,
        intent=negotiation.intent,
        initiator_agent_id=negotiation.initiator_clone_id,
        responder_agent_id=negotiation.responder_clone_id,
        agreed_payload=agreed_payload,
    )
    session_db.add(agreement)
    session_db.flush()
    log_event(
        session_db,
        event_type="agreement_created",
        payload={
            "agreement_id": agreement.id,
            "session_id": negotiation.id,
            "intent": negotiation.intent,
        },
    )
    return agreement


def _handle_envelope(
    session_db: Session, relay: RelayTransport, envelope: dict[str, Any]
) -> dict[str, str]:
    """検証済みエンベロープ1通を状態機械に従って処理する。"""
    message_id = str(envelope.get("message_id", ""))
    session_id = str(envelope.get("session_id", ""))
    message_type = str(envelope.get("message_type", ""))
    sequence = int(envelope.get("sequence", 0))
    sender = str(envelope.get("sender_agent_id", ""))

    negotiation = session_db.get(NegotiationSession, session_id)
    last = _last_message(session_db, session_id) if negotiation else None
    protocol_state.validate_incoming(
        negotiation.status if negotiation else NegotiationStatus.OPEN.value,
        negotiation.last_sequence if negotiation else 0,
        message_type,
        sequence,
        last_message_type=last.message_type if last else "",
        counter_rounds=_counter_rounds(session_db, session_id) if negotiation else 0,
    )

    if message_type == "REQUEST":
        clone = _find_active_clone(session_db)
        negotiation = NegotiationSession(
            id=session_id,
            initiator_clone_id=sender,
            responder_clone_id=clone.id,
            intent=str(envelope.get("intent", INTENT)),
            topic=str(envelope.get("payload", {}).get("topic", "")),
            remote_peer_agent_id=sender,
            last_sequence=sequence,
        )
        session_db.add(negotiation)
        _save_message(session_db, session_id, envelope)
        session_db.commit()
        return {"message_id": message_id, "action": "processed"}

    if negotiation is None:
        raise TwinLinkError(
            code="INVALID_STATE_TRANSITION",
            message="未知のセッションへのメッセージです。",
            status_code=409,
            details={"session_id": session_id},
        )

    _save_message(session_db, session_id, envelope)
    negotiation.last_sequence = sequence

    if message_type in ("PROPOSE", "COUNTER"):
        clone = _find_active_clone(session_db)
        request_payload = _request_payload(session_db, session_id)
        own = _own_candidates(session_db, clone.user_id, request_payload, sender)
        received = [dict(s) for s in envelope.get("delta", {}).get("candidate_slots", [])]
        common = intersect_slots(own, received)
        rounds = _counter_rounds(session_db, session_id) + 1
        if common:
            selected = common[0]
            _send_reply(
                session_db, relay, negotiation, sender, "ACCEPT", sequence + 1,
                {"selected_slot": selected},
            )
            negotiation.status = NegotiationStatus.AGREED.value
            negotiation.result = {"selected_slot": selected, "rounds": rounds}
            _create_remote_agreement(session_db, negotiation, negotiation.result)
        elif rounds < protocol_state.MAX_COUNTER_ROUNDS:
            _send_reply(
                session_db, relay, negotiation, sender, "COUNTER", sequence + 1,
                {"candidate_slots": own[:_OFFER_SIZE]},
            )
        else:
            _send_reply(
                session_db, relay, negotiation, sender, "ERROR", sequence + 1,
                {"code": "NO_AVAILABLE_SLOT"},
            )
            negotiation.status = NegotiationStatus.FAILED.value
            negotiation.result = {"code": "NO_AVAILABLE_SLOT", "rounds": rounds}
    elif message_type == "ACCEPT":
        negotiation.status = NegotiationStatus.AGREED.value
        negotiation.result = {
            "selected_slot": dict(envelope.get("delta", {}).get("selected_slot", {})),
            "rounds": _counter_rounds(session_db, session_id) + 1,
        }
        _create_remote_agreement(session_db, negotiation, negotiation.result)
    elif message_type in ("REJECT", "ERROR"):
        negotiation.status = NegotiationStatus.FAILED.value
        negotiation.result = {"code": str(envelope.get("delta", {}).get("code", message_type))}

    session_db.commit()
    return {"message_id": message_id, "action": "processed"}


def process_inbox(session_db: Session, relay: RelayTransport) -> dict[str, Any]:
    """Relayの受信箱を処理する（受信側）。

    不正なエンベロープはackして拒否を監査記録する（受信箱を詰まらせない）。
    リプレイはackのみで二重処理しない（§35「再送で二重実行されない」）。
    """
    results: list[dict[str, str]] = []

    for delivery in relay.fetch():
        delivery_id = str(delivery["delivery_id"])
        envelope = dict(delivery["envelope"])
        message_id = str(envelope.get("message_id", ""))
        sender = str(envelope.get("sender_agent_id", ""))

        peer = session_db.get(PeerAgent, sender)
        if peer is None or peer.status != PeerStatus.TRUSTED.value:
            relay.ack(delivery_id)
            log_event(
                session_db,
                event_type="envelope_rejected",
                payload={"message_id": message_id, "code": "PEER_NOT_TRUSTED"},
            )
            results.append(
                {"message_id": message_id, "action": "rejected", "code": "PEER_NOT_TRUSTED"}
            )
            continue

        try:
            verify_envelope(envelope, peer.public_key)
        except TwinLinkError as exc:
            relay.ack(delivery_id)
            log_event(
                session_db,
                event_type="envelope_rejected",
                payload={"message_id": message_id, "code": exc.code},
            )
            results.append({"message_id": message_id, "action": "rejected", "code": exc.code})
            continue

        try:
            check_and_record(session_db, message_id)
        except TwinLinkError:
            # 再配送の冪等化: 二重処理せずackのみ（§35）
            relay.ack(delivery_id)
            results.append(
                {"message_id": message_id, "action": "duplicate", "code": "MESSAGE_REPLAYED"}
            )
            continue

        try:
            results.append(_handle_envelope(session_db, relay, envelope))
        except TwinLinkError as exc:
            session_db.rollback()
            relay.ack(delivery_id)
            log_event(
                session_db,
                event_type="envelope_rejected",
                payload={"message_id": message_id, "code": exc.code},
            )
            results.append({"message_id": message_id, "action": "rejected", "code": exc.code})
            continue

        relay.ack(delivery_id)

    log_event(
        session_db,
        event_type="inbox_processed",
        payload={"processed": len(results)},
    )
    return {"processed": len(results), "results": results}
