"""Relay経由の別所有者ノード間交渉（enishi.md §25 v2, §26, §35 Phase 6）。

送信側は署名済みエンベロープをRelayへ送り、受信側は署名・信頼ピア・
リプレイ・状態機械を検証してから日程計算する。busyの本文・予定名・
除外理由は送らない（§17 v2）。監査ログにも本文を残さない。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from enishi_core.config import get_settings
from enishi_core.errors import EnishiError
from enishi_core.models import (
    Agreement,
    Approval,
    ApprovalStatus,
    CloneAgent,
    CloneStatus,
    NegotiationDecision,
    NegotiationMessage,
    NegotiationSession,
    NegotiationStatus,
    PeerAgent,
    PeerStatus,
    PersonalAgent,
    RelayOutbox,
    User,
)
from enishi_core.models.base import utc_now
from enishi_core.security.envelope import build_envelope, verify_envelope
from enishi_core.security.keys import ensure_node_keypair
from enishi_core.security.replay import check_and_record
from enishi_core.services import protocol_state
from enishi_core.services.approvals import create_approval
from enishi_core.services.audit import log_event
from enishi_core.services.decision_evaluator import evaluate_meeting_schedule
from enishi_core.services.memories import exportable_memories
from enishi_core.services.peers import filter_memories_for_peer, get_disclosure_policy
from enishi_core.services.policies import delegation_enabled
from enishi_core.services.public_reasons import to_public_reason
from enishi_core.services.relay_client import RelayTransport
from enishi_core.services.scheduling import (
    Slot,
    candidate_slots,
    collect_busy,
    intersect_slots,
)

INTENT = "meeting.schedule"
_OFFER_SIZE = 5
_PROTOCOL = "aun/0.1"


def _require_trusted_peer(session_db: Session, agent_id: str) -> PeerAgent:
    peer = session_db.get(PeerAgent, agent_id)
    if peer is None or peer.status != PeerStatus.TRUSTED.value:
        raise EnishiError(
            code="PEER_NOT_TRUSTED",
            message="信頼済みでないピアとは交渉できません。",
            status_code=403,
            details={"agent_id": agent_id},
        )
    return peer


def _require_peer_capability(peer: PeerAgent, intent: str) -> None:
    """v2名刺の能力宣言がある場合だけ厳格検証し、v1ピアは互換動作させる。"""
    capabilities = peer.capabilities or {}
    if not capabilities:
        return
    intents = capabilities.get("supported_intents", [])
    protocols = capabilities.get("protocol_versions", [])
    if intent not in intents:
        raise EnishiError(
            code="PEER_CAPABILITY_MISMATCH",
            message="接続相手はこの交渉種別に対応していません。",
            status_code=409,
            details={"intent": intent},
        )
    if _PROTOCOL not in protocols:
        raise EnishiError(
            code="PEER_CAPABILITY_MISMATCH",
            message="接続相手と共通のAUN Protocol versionがありません。",
            status_code=409,
            details={"protocol": _PROTOCOL},
        )


def _find_active_clone(session_db: Session, user_id: str | None = None) -> CloneAgent:
    query = select(CloneAgent).where(CloneAgent.status == CloneStatus.ACTIVE.value)
    if user_id is not None:
        query = query.where(CloneAgent.user_id == user_id)
    clone = session_db.scalars(query.order_by(CloneAgent.created_at.desc())).first()
    if clone is None:
        raise EnishiError(
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
        raise EnishiError(
            code="DISCLOSURE_POLICY_DENIED",
            message="このピアには日程候補を公開しません。",
            status_code=403,
            details={"peer_agent_id": peer_agent_id},
        )
    memories = filter_memories_for_peer(exportable_memories(session_db, user_id), policy)
    user = session_db.get(User, user_id)
    timezone = user.timezone if user else "UTC"
    busy = collect_busy(memories, timezone)
    return candidate_slots(
        dict(request_payload["date_range"]),
        list(request_payload["preferred_time_ranges"]),
        int(request_payload["duration_minutes"]),
        busy,
        timezone,
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


def _enqueue_envelope(
    session_db: Session,
    negotiation: NegotiationSession,
    envelope: dict[str, Any],
    *,
    approval_id: str | None = None,
) -> RelayOutbox:
    outbox = RelayOutbox(
        message_id=str(envelope["message_id"]),
        session_id=negotiation.id,
        approval_id=approval_id,
        envelope=envelope,
    )
    session_db.add(outbox)
    return outbox


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
    peer = _require_trusted_peer(session_db, peer_agent_id)
    _require_peer_capability(peer, INTENT)
    if not delegation_enabled(
        session_db, user_id, "schedule_negotiation", default=True
    ):
        raise EnishiError(
            code="NEGOTIATION_PERMISSION_DENIED",
            message="日程調整は本人代理AIへ委任されていません。",
            status_code=403,
            details={"operation": "schedule_negotiation"},
        )
    from enishi_core.services.agent_requests import (
        ensure_device_node,
        ensure_personal_agent,
    )

    personal = ensure_personal_agent(session_db, user_id)
    if personal.active_clone_id is None:
        _find_active_clone(session_db, user_id)  # 既存エラー形式を維持
    clone = session_db.get(CloneAgent, personal.active_clone_id)
    if clone is None or clone.status != CloneStatus.ACTIVE.value:
        raise EnishiError(
            code="CLONE_REVIEW_REQUIRED",
            message="有効化済みのクローンがありません。",
            status_code=409,
            details={"user_id": user_id},
        )
    node = ensure_device_node(session_db, personal)
    _identity, private_key = ensure_node_keypair(get_settings().data_dir)
    peer_personal_id = peer.personal_agent_id or peer.agent_id
    separated_identity = peer.personal_agent_id is not None
    sender_id = personal.id if separated_identity else node.node_id
    transport_ids = (
        {"sender_node_id": node.node_id, "receiver_node_id": peer.agent_id}
        if separated_identity
        else {}
    )

    user = session_db.get(User, user_id)
    request_payload: dict[str, Any] = {
        "intent": INTENT,
        "topic": topic,
        "duration_minutes": duration_minutes,
        "date_range": date_range,
        "preferred_time_ranges": preferred_time_ranges,
        "timezone": user.timezone if user else "UTC",
    }
    candidates = _own_candidates(session_db, user_id, request_payload, peer_agent_id)[
        :_OFFER_SIZE
    ]

    negotiation = NegotiationSession(
        initiator_clone_id=clone.id,
        responder_clone_id=peer.agent_id,
        initiator_agent_id=personal.id,
        responder_agent_id=peer_personal_id,
        intent=INTENT,
        topic=topic,
        remote_peer_agent_id=peer_agent_id,
        last_sequence=2,
    )
    session_db.add(negotiation)
    session_db.flush()

    # busyの本文・予定名・除外理由は送らない（§17 v2）。構造化リクエストと候補のみ
    request_env = build_envelope(
        sender=sender_id,
        receiver=peer_personal_id,
        session_id=negotiation.id,
        message_type="REQUEST",
        intent=INTENT,
        session_version=negotiation.session_version,
        sequence=1,
        payload=request_payload,
        delta={},
        requires_human_approval=False,
        private_key=private_key,
        **transport_ids,
    )
    propose_env = build_envelope(
        sender=sender_id,
        receiver=peer_personal_id,
        session_id=negotiation.id,
        message_type="PROPOSE",
        intent=INTENT,
        session_version=negotiation.session_version,
        sequence=2,
        payload={},
        delta={"candidate_slots": candidates},
        requires_human_approval=False,
        private_key=private_key,
        **transport_ids,
    )
    _save_message(session_db, negotiation.id, request_env)
    _save_message(session_db, negotiation.id, propose_env)
    _enqueue_envelope(session_db, negotiation, request_env)
    _enqueue_envelope(session_db, negotiation, propose_env)
    session_db.commit()
    session_db.refresh(negotiation)

    # DB確定後にだけ外部送信する。失敗時はpendingのままワーカーが再送する。
    flush_outbox(session_db, relay)

    log_event(
        session_db,
        event_type="remote_negotiation_started",
        payload={"session_id": negotiation.id, "peer_agent_id": peer_agent_id},
    )
    return negotiation


def _last_message(session_db: Session, session_id: str) -> NegotiationMessage | None:
    return session_db.scalars(
        select(NegotiationMessage)
        .where(
            NegotiationMessage.session_id == session_id,
            NegotiationMessage.message_type.not_in(
                ("REQUEST_APPROVAL", "APPROVAL_RESULT")
            ),
        )
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
        raise EnishiError(
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
    sender: str,
    receiver: str,
    receiver_node_id: str,
    message_type: str,
    sequence: int,
    delta: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> None:
    envelope = _build_reply_envelope(
        session_db,
        negotiation,
        sender,
        receiver,
        receiver_node_id,
        message_type,
        sequence,
        delta,
        payload,
    )
    _save_message(session_db, negotiation.id, envelope)
    _enqueue_envelope(session_db, negotiation, envelope)
    negotiation.last_sequence = sequence


def _build_reply_envelope(
    session_db: Session,
    negotiation: NegotiationSession,
    sender: str,
    receiver: str,
    receiver_node_id: str,
    message_type: str,
    sequence: int,
    delta: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity, private_key = ensure_node_keypair(get_settings().data_dir)
    transport_ids: dict[str, str] = {}
    sender_id = identity.agent_id
    if negotiation.responder_agent_id is not None:
        personal = session_db.get(PersonalAgent, sender)
        if personal is None:
            raise EnishiError(
                code="AGENT_IDENTITY_MISMATCH",
                message="本人エージェントIDを確認できません。",
                status_code=403,
                details={"sender_agent_id": sender},
            )
        from enishi_core.services.agent_requests import ensure_device_node

        node = ensure_device_node(session_db, personal)
        sender_id = personal.id
        transport_ids = {
            "sender_node_id": node.node_id,
            "receiver_node_id": receiver_node_id,
        }
    return build_envelope(
        sender=sender_id,
        receiver=receiver,
        session_id=negotiation.id,
        message_type=message_type,
        intent=INTENT,
        session_version=negotiation.session_version,
        sequence=sequence,
        payload=payload or {},
        delta=delta,
        requires_human_approval=False,
        private_key=private_key,
        **transport_ids,
    )


def _create_remote_agreement(
    session_db: Session,
    negotiation: NegotiationSession,
    agreed_payload: dict[str, Any],
) -> Agreement:
    """リモートACCEPT終端を合意として保存する（enishi.md 方針修正 §4）。"""
    existing = session_db.scalars(
        select(Agreement).where(Agreement.session_id == negotiation.id)
    ).first()
    if existing is not None:
        return existing
    agreement = Agreement(
        session_id=negotiation.id,
        intent=negotiation.intent,
        initiator_agent_id=negotiation.initiator_agent_id or negotiation.initiator_clone_id,
        responder_agent_id=negotiation.responder_agent_id or negotiation.responder_clone_id,
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


def _meeting_agreement_payload(selected_slot: dict[str, Any]) -> dict[str, Any]:
    """両ノードで一致する、合意そのものだけをwire由来データから構成する。"""
    return {"selected_slot": dict(selected_slot)}


def _record_decision(
    session_db: Session,
    negotiation: NegotiationSession,
    clone: CloneAgent,
    *,
    common_slot_count: int,
    selected_slot: dict[str, Any] | None,
    peer_personal_agent_id: str,
) -> NegotiationDecision:
    user = session_db.get(User, clone.user_id)
    evaluation = evaluate_meeting_schedule(
        clone=clone,
        delegation_enabled=delegation_enabled(
            session_db, clone.user_id, "schedule_negotiation", default=True
        ),
        common_slot_count=common_slot_count,
        selected_slot=selected_slot,
        peer_personal_agent_id=peer_personal_agent_id,
        timezone=user.timezone if user else "UTC",
    )
    decision = NegotiationDecision(
        session_id=negotiation.id,
        clone_id=clone.id,
        policy_version=evaluation.policy_version,
        outcome=evaluation.outcome,
        reason_codes=evaluation.reason_codes,
        evidence=evaluation.evidence,
        confidence=evaluation.confidence,
    )
    session_db.add(decision)
    session_db.flush()
    return decision


def _request_human_decision(
    session_db: Session,
    negotiation: NegotiationSession,
    clone: CloneAgent,
    decision: NegotiationDecision,
    *,
    selected_slot: dict[str, Any] | None,
    candidate_slots: list[dict[str, Any]],
    peer_node_id: str,
    peer_personal_agent_id: str,
) -> Approval:
    approval = create_approval(
        session_db,
        user_id=clone.user_id,
        action_type="negotiation_decision",
        description="代理AIの交渉案について本人の判断が必要です。",
        level=1,
        payload={
            "session_id": negotiation.id,
            "intent": negotiation.intent,
            "remote": True,
            "proposed_action": "ACCEPT" if selected_slot else "COUNTER",
            "selected_slot": selected_slot or {},
            "candidate_slots": candidate_slots,
            "reason_codes": list(decision.reason_codes),
            "decision_confidence": decision.confidence,
            "peer_node_id": peer_node_id,
            "peer_personal_agent_id": peer_personal_agent_id,
        },
        commit=False,
    )
    negotiation.status = NegotiationStatus.WAITING_APPROVAL.value
    negotiation.pending_approval_id = approval.id
    # REQUEST_APPROVALはローカルのApproval/Decisionとして保持する。
    # wireと共用するsequenceへ疑似メッセージを加えると、次の正規応答と
    # 順序が衝突するためNegotiationMessageには保存しない。
    return approval


def flush_outbox(session_db: Session, relay: RelayTransport) -> dict[str, int]:
    """固定message_idの署名済みEnvelopeを送る。失敗時はpendingのまま残す。"""
    pending = list(
        session_db.scalars(
            select(RelayOutbox)
            .where(RelayOutbox.status == "pending")
            .order_by(RelayOutbox.created_at)
        )
    )
    sent = 0
    failed = 0
    for item in pending:
        item.attempts += 1
        try:
            relay.send(dict(item.envelope))
        except Exception as exc:  # RelayTransport実装差を越えて永続キューへ記録する
            item.last_error = str(exc)[:500]
            failed += 1
            session_db.commit()
            # 同一セッションの後続メッセージが先行しないよう、順序を保って止める。
            break
        item.status = "sent"
        item.sent_at = utc_now()
        item.last_error = None
        sent += 1
        session_db.commit()
    return {"sent": sent, "failed": failed, "pending": len(pending) - sent}


def resolve_remote_approval(
    session_db: Session,
    approval_id: str,
    target_status: str,
    selected_slot_override: dict[str, str] | None = None,
) -> Approval:
    """リモート交渉承認を一度だけ解決し、応答をOutboxへ原子的に保存する。"""
    approval = session_db.get(Approval, approval_id)
    if approval is None:
        raise EnishiError(
            code="APPROVAL_REQUIRED",
            message="承認対象が見つかりません。",
            status_code=404,
            details={"approval_id": approval_id},
        )
    if approval.action_type != "negotiation_decision" or not approval.payload.get(
        "remote"
    ):
        raise EnishiError(
            code="INVALID_STATE_TRANSITION",
            message="リモート交渉の承認ではありません。",
            status_code=409,
        )
    if approval.status != ApprovalStatus.PENDING.value:
        raise EnishiError(
            code=(
                "APPROVAL_EXPIRED"
                if approval.status == ApprovalStatus.EXPIRED.value
                else "INVALID_STATE_TRANSITION"
            ),
            message=f"状態 {approval.status} からは変更できません。",
            status_code=409,
            details={"status": approval.status},
        )
    if target_status not in {
        ApprovalStatus.APPROVED.value,
        ApprovalStatus.REJECTED.value,
        ApprovalStatus.EXPIRED.value,
    }:
        raise ValueError(f"unsupported approval status: {target_status}")

    session_id = str(approval.payload.get("session_id", ""))
    negotiation = session_db.get(NegotiationSession, session_id)
    if (
        negotiation is None
        or negotiation.status != NegotiationStatus.WAITING_APPROVAL.value
        or negotiation.pending_approval_id != approval.id
    ):
        raise EnishiError(
            code="INVALID_STATE_TRANSITION",
            message="承認待ちの交渉を確認できません。",
            status_code=409,
            details={"session_id": session_id},
        )

    approved = target_status == ApprovalStatus.APPROVED.value
    selected_slot = dict(approval.payload.get("selected_slot", {}))
    candidate_slots = [
        dict(slot) for slot in approval.payload.get("candidate_slots", [])
        if isinstance(slot, dict)
    ]
    proposed_action = str(approval.payload.get("proposed_action", "ACCEPT"))
    if approved and selected_slot_override is not None:
        override = dict(selected_slot_override)
        if override not in candidate_slots:
            raise EnishiError(
                code="INVALID_APPROVAL_SELECTION",
                message="選択した候補は、この承認に含まれていません。",
                status_code=422,
                details={"approval_id": approval.id},
            )
        proposed_action = "ACCEPT" if override == selected_slot else "COUNTER"
        selected_slot = override
    message_type = proposed_action if approved else "REJECT"
    delta: dict[str, Any]
    if approved and message_type == "ACCEPT":
        delta = {"selected_slot": selected_slot}
    elif approved and message_type == "COUNTER":
        counter_slots = [selected_slot] if selected_slot else candidate_slots[:_OFFER_SIZE]
        delta = {"candidate_slots": counter_slots}
    else:
        delta = {
            "code": "HUMAN_REJECTED"
            if target_status == "rejected"
            else "APPROVAL_EXPIRED"
        }
    public_payload: dict[str, Any] = {}
    if message_type == "COUNTER":
        public_payload = {
            "public_reason": to_public_reason(
                [str(code) for code in approval.payload.get("reason_codes", [])]
            )
        }
    elif message_type == "REJECT":
        public_payload = {
            "public_reason": to_public_reason(
                [
                    "approval_expired"
                    if target_status == ApprovalStatus.EXPIRED.value
                    else "human_rejected"
                ]
            )
        }
    own_personal_id = negotiation.responder_agent_id or ""
    peer_personal_id = str(
        approval.payload.get("peer_personal_agent_id")
        or negotiation.initiator_agent_id
        or negotiation.initiator_clone_id
    )
    peer_node_id = str(
        approval.payload.get("peer_node_id") or negotiation.remote_peer_agent_id or ""
    )
    sequence = negotiation.last_sequence + 1
    envelope = _build_reply_envelope(
        session_db,
        negotiation,
        own_personal_id,
        peer_personal_id,
        peer_node_id,
        message_type,
        sequence,
        delta,
        public_payload,
    )
    _save_message(session_db, negotiation.id, envelope)
    _enqueue_envelope(
        session_db, negotiation, envelope, approval_id=approval.id
    )
    negotiation.last_sequence = sequence
    negotiation.pending_approval_id = None
    approval.status = target_status
    approval.resolved_at = utc_now()
    if approved and message_type == "ACCEPT":
        negotiation.status = NegotiationStatus.AGREED.value
        negotiation.result = {"selected_slot": selected_slot, "approved_by_human": True}
        _create_remote_agreement(
            session_db, negotiation, _meeting_agreement_payload(selected_slot)
        )
    elif approved:
        negotiation.status = NegotiationStatus.OPEN.value
        negotiation.result = {"counter_approved_by_human": True}
    else:
        negotiation.status = NegotiationStatus.FAILED.value
        negotiation.result = {"code": delta["code"], "resolved_by_human": True}
    session_db.commit()
    session_db.refresh(approval)
    log_event(
        session_db,
        event_type=f"approval_{target_status}",
        user_id=approval.user_id,
        payload={"approval_id": approval.id, "action_type": approval.action_type},
    )
    return approval


def _handle_envelope(
    session_db: Session, relay: RelayTransport, envelope: dict[str, Any]
) -> dict[str, str]:
    """検証済みエンベロープ1通を状態機械に従って処理する。"""
    message_id = str(envelope.get("message_id", ""))
    session_id = str(envelope.get("session_id", ""))
    message_type = str(envelope.get("message_type", ""))
    sequence = int(envelope.get("sequence", 0))
    sender = str(envelope.get("sender_agent_id", ""))
    sender_node = str(envelope.get("sender_node_id", sender))
    receiver = str(envelope.get("receiver_agent_id", ""))

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
        if "sender_node_id" in envelope:
            personal = session_db.get(PersonalAgent, receiver)
            if personal is None or personal.active_clone_id is None:
                raise EnishiError(
                    code="AGENT_IDENTITY_MISMATCH",
                    message="宛先の本人エージェントを確認できません。",
                    status_code=403,
                )
            clone = session_db.get(CloneAgent, personal.active_clone_id)
            if clone is None:
                raise EnishiError(
                    code="CLONE_REVIEW_REQUIRED",
                    message="有効化済みのクローンがありません。",
                    status_code=409,
                )
            responder_id = clone.id
        else:
            responder_id = _find_active_clone(session_db).id
        negotiation = NegotiationSession(
            id=session_id,
            initiator_clone_id=sender,
            responder_clone_id=responder_id,
            initiator_agent_id=sender if "sender_node_id" in envelope else None,
            responder_agent_id=receiver if "sender_node_id" in envelope else None,
            intent=str(envelope.get("intent", INTENT)),
            topic=str(envelope.get("payload", {}).get("topic", "")),
            remote_peer_agent_id=sender_node,
            last_sequence=sequence,
        )
        session_db.add(negotiation)
        _save_message(session_db, session_id, envelope)
        session_db.commit()
        return {"message_id": message_id, "action": "processed"}

    if negotiation is None:
        raise EnishiError(
            code="INVALID_STATE_TRANSITION",
            message="未知のセッションへのメッセージです。",
            status_code=409,
            details={"session_id": session_id},
        )

    _save_message(session_db, session_id, envelope)
    negotiation.last_sequence = sequence

    if message_type in ("PROPOSE", "COUNTER"):
        personal = None
        if negotiation.responder_agent_id is not None:
            personal = session_db.get(PersonalAgent, negotiation.responder_agent_id)
            if personal is None or personal.active_clone_id is None:
                raise EnishiError(
                    code="CLONE_REVIEW_REQUIRED",
                    message="有効化済みのクローンがありません。",
                    status_code=409,
                )
            clone = session_db.get(CloneAgent, personal.active_clone_id)
            if clone is None or clone.status != CloneStatus.ACTIVE.value:
                raise EnishiError(
                    code="CLONE_REVIEW_REQUIRED",
                    message="有効化済みのクローンがありません。",
                    status_code=409,
                )
        else:
            clone = _find_active_clone(session_db)
        request_payload = _request_payload(session_db, session_id)
        own = _own_candidates(session_db, clone.user_id, request_payload, sender_node)
        received = [dict(s) for s in envelope.get("delta", {}).get("candidate_slots", [])]
        common = intersect_slots(own, received)
        rounds = _counter_rounds(session_db, session_id) + 1
        sender_personal_id = personal.id if personal else ""
        decision = _record_decision(
            session_db,
            negotiation,
            clone,
            common_slot_count=len(common),
            selected_slot=common[0] if common else None,
            peer_personal_agent_id=sender,
        )
        if decision.outcome == "approval_required":
            _request_human_decision(
                session_db,
                negotiation,
                clone,
                decision,
                selected_slot=common[0] if common else None,
                candidate_slots=own[:_OFFER_SIZE],
                peer_node_id=sender_node,
                peer_personal_agent_id=sender,
            )
            session_db.commit()
            return {"message_id": message_id, "action": "approval_required"}
        if common:
            selected = common[0]
            _send_reply(
                session_db, relay, negotiation, sender_personal_id, sender, sender_node,
                "ACCEPT", sequence + 1,
                {"selected_slot": selected},
            )
            negotiation.status = NegotiationStatus.AGREED.value
            negotiation.result = {"selected_slot": selected, "rounds": rounds}
            _create_remote_agreement(
                session_db, negotiation, _meeting_agreement_payload(selected)
            )
        elif rounds < protocol_state.MAX_COUNTER_ROUNDS:
            _send_reply(
                session_db, relay, negotiation, sender_personal_id, sender, sender_node,
                "COUNTER", sequence + 1,
                {"candidate_slots": own[:_OFFER_SIZE]},
                {"public_reason": to_public_reason(decision.reason_codes)},
            )
        else:
            _send_reply(
                session_db, relay, negotiation, sender_personal_id, sender, sender_node,
                "ERROR", sequence + 1,
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
        _create_remote_agreement(
            session_db,
            negotiation,
            _meeting_agreement_payload(negotiation.result["selected_slot"]),
        )
    elif message_type in ("REJECT", "ERROR"):
        negotiation.status = NegotiationStatus.FAILED.value
        negotiation.result = {
            "code": str(envelope.get("delta", {}).get("code", message_type)),
            "public_reason": str(envelope.get("payload", {}).get("public_reason", "")),
        }

    session_db.commit()
    return {"message_id": message_id, "action": "processed"}


def process_inbox(session_db: Session, relay: RelayTransport) -> dict[str, Any]:
    """Relayの受信箱を処理する（受信側）。

    不正なエンベロープはackして拒否を監査記録する（受信箱を詰まらせない）。
    リプレイはackのみで二重処理しない（§35「再送で二重実行されない」）。
    """
    results: list[dict[str, str]] = []

    for delivery in relay.fetch():
        delivery_id = str(delivery.get("delivery_id", ""))
        raw_envelope = delivery.get("envelope")
        if not delivery_id or not isinstance(raw_envelope, dict):
            if delivery_id:
                relay.ack(delivery_id)
            log_event(
                session_db,
                event_type="envelope_rejected",
                payload={"message_id": "", "code": "MESSAGE_SCHEMA_INVALID"},
            )
            results.append(
                {
                    "message_id": "",
                    "action": "rejected",
                    "code": "MESSAGE_SCHEMA_INVALID",
                }
            )
            continue
        envelope = dict(raw_envelope)
        message_id = str(envelope.get("message_id", ""))
        sender = str(envelope.get("sender_agent_id", ""))
        sender_node = str(envelope.get("sender_node_id", sender))
        receiver = str(envelope.get("receiver_agent_id", ""))
        receiver_node = str(envelope.get("receiver_node_id", receiver))

        peer = session_db.get(PeerAgent, sender_node)
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

        mapped_personal_id = peer.personal_agent_id or peer.agent_id
        is_separated_identity = "sender_node_id" in envelope
        local_identity, _private_key = ensure_node_keypair(get_settings().data_dir)
        local_personal = session_db.get(PersonalAgent, receiver)
        if (
            (is_separated_identity and mapped_personal_id != sender)
            or (is_separated_identity and receiver_node != local_identity.agent_id)
            or (is_separated_identity and local_personal is None)
        ):
            relay.ack(delivery_id)
            log_event(
                session_db,
                event_type="envelope_rejected",
                payload={"message_id": message_id, "code": "AGENT_IDENTITY_MISMATCH"},
            )
            results.append(
                {
                    "message_id": message_id,
                    "action": "rejected",
                    "code": "AGENT_IDENTITY_MISMATCH",
                }
            )
            continue

        try:
            verify_envelope(envelope, peer.public_key)
        except EnishiError as exc:
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
        except EnishiError:
            # 再配送の冪等化: 二重処理せずackのみ（§35）
            relay.ack(delivery_id)
            results.append(
                {"message_id": message_id, "action": "duplicate", "code": "MESSAGE_REPLAYED"}
            )
            continue

        try:
            results.append(_handle_envelope(session_db, relay, envelope))
        except EnishiError as exc:
            session_db.rollback()
            relay.ack(delivery_id)
            log_event(
                session_db,
                event_type="envelope_rejected",
                payload={"message_id": message_id, "code": exc.code},
            )
            results.append({"message_id": message_id, "action": "rejected", "code": exc.code})
            continue
        except Exception:
            # 署名後のpayload変換等で未知の例外が起きても配送単位で隔離する。
            session_db.rollback()
            relay.ack(delivery_id)
            log_event(
                session_db,
                event_type="envelope_rejected",
                payload={"message_id": message_id, "code": "MESSAGE_PROCESSING_FAILED"},
            )
            results.append(
                {
                    "message_id": message_id,
                    "action": "rejected",
                    "code": "MESSAGE_PROCESSING_FAILED",
                }
            )
            continue

        # 応答は処理トランザクションでOutboxへ確定済み。送信失敗でも受信はackできる。
        flush_outbox(session_db, relay)
        relay.ack(delivery_id)

    log_event(
        session_db,
        event_type="inbox_processed",
        payload={"processed": len(results)},
    )
    return {"processed": len(results), "results": results}
