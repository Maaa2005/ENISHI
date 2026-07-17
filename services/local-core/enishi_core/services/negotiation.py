"""構造化交渉（enishi.md §25, §27, §28）。

2クローン間の日程調整を決定的に実行する（LLM不使用）。
2通目以降のメッセージは差分だけをdeltaへ入れる（§25）。
交渉完了後、構造化方式とメール方式のトークン消費を実測して記録する（§28）。
仕事依頼は同じ状態機械で処理する（enishi.md 方針修正 §4）。
"""

from datetime import UTC, date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from enishi_core.errors import EnishiError
from enishi_core.models import (
    Agreement,
    AgreementStatus,
    Approval,
    ApprovalStatus,
    CloneAgent,
    MessageType,
    NegotiationMessage,
    NegotiationSession,
    NegotiationStatus,
    TokenMetric,
    User,
)
from enishi_core.models.base import utc_now
from enishi_core.services import approvals as approval_service
from enishi_core.services.audit import log_event
from enishi_core.services.memories import exportable_memories
from enishi_core.services.policies import delegation_enabled
from enishi_core.services.public_reasons import to_public_reason
from enishi_core.services.scheduling import (
    Slot,
    candidate_slots,
    collect_busy,
    intersect_slots,
)
from enishi_core.services.token_counter import estimate_json_tokens, estimate_tokens

_MAX_ROUNDS = 3
_OFFER_SIZE = 5
INTENT_MEETING_SCHEDULE = "meeting.schedule"
INTENT_TASK_REQUEST = "task.request"


def _require_active_clone(session_db: Session, user_id: str) -> CloneAgent:
    from enishi_core.services.clones import get_active_clone

    clone = get_active_clone(session_db, user_id)
    if clone is None:
        raise EnishiError(
            code="CLONE_REVIEW_REQUIRED",
            message="有効化済みのクローンがありません。",
            status_code=409,
            details={"user_id": user_id},
        )
    return clone


def _slot_label(slot: Slot) -> str:
    return f"{slot['start']}〜{slot['end'].split('T')[-1]}"


def _create_agreement(
    session_db: Session,
    negotiation: NegotiationSession,
    agreed_payload: dict[str, Any],
) -> Agreement:
    """ACCEPTで終端した合意を保存する（enishi.md 方針修正 §4）。"""
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


def build_email_transcript(
    topic: str,
    duration_minutes: int,
    offers: list[list[Slot]],
    selected_slot: Slot | None,
) -> list[str]:
    """同じ交渉をメール往復で行った場合の文面を組み立てる（テンプレート、LLM不使用）。"""
    emails: list[str] = [
        f"お世話になっております。\n\n"
        f"{topic}について{duration_minutes}分ほどお時間をいただきたく、"
        f"ご連絡いたしました。\n"
        f"ご都合のよい日時の候補をいくつかお知らせいただけますでしょうか。\n\n"
        f"何卒よろしくお願いいたします。"
    ]
    for offer in offers:
        lines = "\n".join(f"・{_slot_label(slot)}" for slot in offer)
        emails.append(
            f"ご連絡ありがとうございます。\n\n"
            f"こちらの都合のよい候補は以下のとおりです。\n{lines}\n\n"
            f"上記でご都合いかがでしょうか。\n"
            f"よろしくお願いいたします。"
        )
    if selected_slot is not None:
        emails.append(
            f"ありがとうございます。\n\n"
            f"それでは {_slot_label(selected_slot)} でお願いいたします。\n"
            f"当日はどうぞよろしくお願いいたします。"
        )
    else:
        emails.append(
            "ご確認ありがとうございました。\n\n"
            "あいにく都合の合う時間が見つかりませんでした。\n"
            "別の週で改めて調整させてください。\n"
            "よろしくお願いいたします。"
        )
    return emails


def _record_metrics(
    session_db: Session,
    negotiation: NegotiationSession,
    messages: list[NegotiationMessage],
    offers: list[list[Slot]],
    selected_slot: Slot | None,
    topic: str,
    duration_minutes: int,
) -> None:
    """交渉の実測トークンを記録する（§28。固定値ではなく生成物から計算する）。"""
    structured_total = sum(
        estimate_json_tokens(m.payload) + estimate_json_tokens(m.delta) for m in messages
    )
    emails = build_email_transcript(topic, duration_minutes, offers, selected_slot)
    email_total = sum(estimate_tokens(email) for email in emails)

    session_db.add(
        TokenMetric(
            session_id=negotiation.id,
            method="structured",
            input_tokens=structured_total // 2,
            output_tokens=structured_total - structured_total // 2,
            llm_calls=0,
            message_count=len(messages),
        )
    )
    session_db.add(
        TokenMetric(
            session_id=negotiation.id,
            method="email",
            input_tokens=email_total // 2,
            output_tokens=email_total - email_total // 2,
            llm_calls=len(emails),
            message_count=len(emails),
        )
    )
    session_db.commit()


def run_negotiation(
    session_db: Session,
    initiator_user_id: str,
    responder_user_id: str,
    topic: str,
    duration_minutes: int,
    date_range: dict[str, str],
    preferred_time_ranges: list[dict[str, str]],
) -> NegotiationSession:
    """日程調整の交渉を同期実行する。日程計算はPythonコードで行う（§27）。"""
    initiator = _require_active_clone(session_db, initiator_user_id)
    responder = _require_active_clone(session_db, responder_user_id)

    initiator_user = session_db.get(User, initiator_user_id)
    responder_user = session_db.get(User, responder_user_id)
    initiator_timezone = initiator_user.timezone if initiator_user else "UTC"
    responder_timezone = responder_user.timezone if responder_user else "UTC"
    initiator_busy = collect_busy(
        exportable_memories(session_db, initiator_user_id), initiator_timezone
    )
    responder_busy = collect_busy(
        exportable_memories(session_db, responder_user_id), responder_timezone
    )
    initiator_candidates = candidate_slots(
        date_range,
        preferred_time_ranges,
        duration_minutes,
        initiator_busy,
        initiator_timezone,
    )
    responder_candidates = candidate_slots(
        date_range,
        preferred_time_ranges,
        duration_minutes,
        responder_busy,
        responder_timezone,
    )

    negotiation = NegotiationSession(
        initiator_clone_id=initiator.id,
        responder_clone_id=responder.id,
        intent=INTENT_MEETING_SCHEDULE,
        topic=topic,
    )
    session_db.add(negotiation)
    session_db.commit()
    session_db.refresh(negotiation)

    messages: list[NegotiationMessage] = []

    def add_message(
        sender: CloneAgent,
        receiver: CloneAgent,
        message_type: MessageType,
        payload: dict[str, Any] | None = None,
        delta: dict[str, Any] | None = None,
    ) -> NegotiationMessage:
        message = NegotiationMessage(
            session_id=negotiation.id,
            sequence=len(messages) + 1,
            sender_agent_id=sender.id,
            receiver_agent_id=receiver.id,
            message_type=message_type.value,
            intent=INTENT_MEETING_SCHEDULE,
            payload=payload or {},
            delta=delta or {},
        )
        session_db.add(message)
        messages.append(message)
        return message

    # 初回のみ全体を送り、以降は差分のみdeltaで送る（§25）
    add_message(
        initiator,
        responder,
        MessageType.REQUEST,
        payload={
            "intent": INTENT_MEETING_SCHEDULE,
            "topic": topic,
            "duration_minutes": duration_minutes,
            "date_range": date_range,
            "preferred_time_ranges": preferred_time_ranges,
            "timezone": initiator_timezone,
        },
    )

    candidates_by_clone = {initiator.id: initiator_candidates, responder.id: responder_candidates}
    offers: list[list[Slot]] = []
    selected_slot: Slot | None = None
    rounds = 0

    current_offer = initiator_candidates[:_OFFER_SIZE]
    offers.append(current_offer)
    add_message(
        initiator, responder, MessageType.PROPOSE, delta={"candidate_slots": current_offer}
    )

    sender, receiver = initiator, responder
    for round_number in range(1, _MAX_ROUNDS + 1):
        rounds = round_number
        common = intersect_slots(candidates_by_clone[receiver.id], current_offer)
        if common:
            selected_slot = common[0]
            add_message(
                receiver, sender, MessageType.ACCEPT, delta={"selected_slot": selected_slot}
            )
            negotiation.status = NegotiationStatus.AGREED.value
            negotiation.result = {"selected_slot": selected_slot, "rounds": rounds}
            _create_agreement(session_db, negotiation, negotiation.result)
            break
        if round_number == _MAX_ROUNDS:
            add_message(receiver, sender, MessageType.ERROR, delta={"code": "NO_AVAILABLE_SLOT"})
            negotiation.status = NegotiationStatus.FAILED.value
            negotiation.result = {"code": "NO_AVAILABLE_SLOT", "rounds": rounds}
            break
        counter_offer = candidates_by_clone[receiver.id][:_OFFER_SIZE]
        offers.append(counter_offer)
        add_message(
            receiver,
            sender,
            MessageType.COUNTER,
            payload={"public_reason": "no_common_slot"},
            delta={"candidate_slots": counter_offer},
        )
        current_offer = counter_offer
        sender, receiver = receiver, sender

    session_db.commit()
    session_db.refresh(negotiation)

    _record_metrics(
        session_db, negotiation, messages, offers, selected_slot, topic, duration_minutes
    )
    log_event(
        session_db,
        event_type="negotiation_completed",
        payload={
            "session_id": negotiation.id,
            "status": negotiation.status,
            "message_count": len(messages),
            "rounds": rounds,
        },
    )
    return negotiation


def _deadline_margin_ok(deadline: str | None, min_days: int) -> bool:
    if deadline is None:
        return True
    deadline_date = date.fromisoformat(deadline)
    today = utc_now().astimezone(UTC).date()
    return (deadline_date - today).days >= min_days


def _task_policy(clone: CloneAgent) -> dict[str, Any]:
    raw = clone.policy_profile.get("task_request", {})
    policy = raw if isinstance(raw, dict) else {}
    return {
        "max_hours_auto_accept": float(policy.get("max_hours_auto_accept", 2.0)),
        "max_hours_auto_counter": float(policy.get("max_hours_auto_counter", 4.0)),
        "min_deadline_margin_days": int(policy.get("min_deadline_margin_days", 1)),
    }


def _counter_deadline(deadline: str | None, min_days: int) -> str | None:
    if deadline is None or _deadline_margin_ok(deadline, min_days):
        return deadline
    return (utc_now().astimezone(UTC).date() + timedelta(days=min_days)).isoformat()


def _create_negotiation_approval(
    session_db: Session,
    responder: CloneAgent,
    negotiation: NegotiationSession,
    payload: dict[str, Any],
    reason: str,
) -> Approval:
    approval = approval_service.create_approval(
        session_db,
        user_id=responder.user_id,
        action_type="negotiation_decision",
        description=f"交渉 {negotiation.id} の最終判断が必要です。",
        level=1,
        payload={
            "session_id": negotiation.id,
            "intent": negotiation.intent,
            "reason": reason,
            "proposed_action": "ACCEPT",
            "payload": payload,
        },
    )
    negotiation.status = NegotiationStatus.WAITING_APPROVAL.value
    negotiation.pending_approval_id = approval.id
    session_db.add(
        NegotiationMessage(
            session_id=negotiation.id,
            sequence=2,
            sender_agent_id=responder.id,
            receiver_agent_id=negotiation.initiator_clone_id,
            message_type=MessageType.REQUEST_APPROVAL.value,
            intent=negotiation.intent,
            payload={},
            delta={"approval_id": approval.id, "reason": reason},
            requires_human_approval=True,
        )
    )
    session_db.commit()
    session_db.refresh(negotiation)
    return approval


def run_task_request_negotiation(
    session_db: Session,
    initiator_user_id: str,
    responder_user_id: str,
    title: str,
    description: str = "",
    deadline: str | None = None,
    estimated_hours: float | None = None,
    conditions: dict[str, Any] | None = None,
) -> NegotiationSession:
    """仕事依頼を日程調整と同じ状態機械で交渉する（enishi.md 方針修正 §4）。"""
    initiator = _require_active_clone(session_db, initiator_user_id)
    responder = _require_active_clone(session_db, responder_user_id)
    task_payload: dict[str, Any] = {
        "intent": INTENT_TASK_REQUEST,
        "title": title,
        "description": description,
        "deadline": deadline,
        "estimated_hours": estimated_hours,
        "conditions": conditions or {},
    }
    if not delegation_enabled(session_db, responder.user_id, "task_negotiation", default=True):
        negotiation = NegotiationSession(
            initiator_clone_id=initiator.id,
            responder_clone_id=responder.id,
            intent=INTENT_TASK_REQUEST,
            topic=title,
        )
        session_db.add(negotiation)
        session_db.flush()
        session_db.add(
            NegotiationMessage(
                session_id=negotiation.id,
                sequence=1,
                sender_agent_id=initiator.id,
                receiver_agent_id=responder.id,
                message_type=MessageType.REQUEST.value,
                intent=INTENT_TASK_REQUEST,
                payload=task_payload,
                delta={},
            )
        )
        _create_negotiation_approval(
            session_db,
            responder,
            negotiation,
            task_payload,
            reason="task_negotiation_not_delegated",
        )
        return negotiation
    negotiation = NegotiationSession(
        initiator_clone_id=initiator.id,
        responder_clone_id=responder.id,
        intent=INTENT_TASK_REQUEST,
        topic=title,
    )
    session_db.add(negotiation)
    session_db.flush()
    messages: list[NegotiationMessage] = [
        NegotiationMessage(
            session_id=negotiation.id,
            sequence=1,
            sender_agent_id=initiator.id,
            receiver_agent_id=responder.id,
            message_type=MessageType.REQUEST.value,
            intent=INTENT_TASK_REQUEST,
            payload=task_payload,
            delta={},
        )
    ]
    session_db.add(messages[0])

    policy = _task_policy(responder)
    hours = float(estimated_hours or 0.0)
    max_accept = float(policy["max_hours_auto_accept"])
    max_counter = float(policy["max_hours_auto_counter"])
    min_days = int(policy["min_deadline_margin_days"])
    deadline_ok = _deadline_margin_ok(deadline, min_days)

    if hours <= max_accept and deadline_ok:
        accepted = dict(task_payload)
        message = NegotiationMessage(
            session_id=negotiation.id,
            sequence=2,
            sender_agent_id=responder.id,
            receiver_agent_id=initiator.id,
            message_type=MessageType.ACCEPT.value,
            intent=INTENT_TASK_REQUEST,
            payload={},
            delta={"accepted_task": accepted},
        )
        session_db.add(message)
        messages.append(message)
        negotiation.status = NegotiationStatus.AGREED.value
        negotiation.result = {"accepted_task": accepted, "rounds": 1}
        _create_agreement(session_db, negotiation, accepted)
        session_db.commit()
        session_db.refresh(negotiation)
        return negotiation

    if hours <= max_counter:
        counter: dict[str, Any] = dict(task_payload)
        if hours > max_accept:
            counter["estimated_hours"] = max_accept
            counter_conditions = counter.setdefault("conditions", {})
            if isinstance(counter_conditions, dict):
                counter_conditions["scope"] = "reduce_to_auto_accept_hours"
        counter["deadline"] = _counter_deadline(deadline, min_days)
        message = NegotiationMessage(
            session_id=negotiation.id,
            sequence=2,
            sender_agent_id=responder.id,
            receiver_agent_id=initiator.id,
            message_type=MessageType.COUNTER.value,
            intent=INTENT_TASK_REQUEST,
            payload={
                "public_reason": to_public_reason(
                    ["task_request_policy_threshold_exceeded"]
                )
            },
            delta={"proposed_task": counter},
        )
        session_db.add(message)
        negotiation.result = {"proposed_task": counter, "rounds": 1}
        session_db.commit()
        session_db.refresh(negotiation)
        return negotiation

    _create_negotiation_approval(
        session_db,
        responder,
        negotiation,
        task_payload,
        reason="task_request_policy_threshold_exceeded",
    )
    return negotiation


def list_negotiations(session_db: Session, limit: int = 20) -> list[NegotiationSession]:
    from sqlalchemy import select

    return list(
        session_db.scalars(
            select(NegotiationSession)
            .order_by(NegotiationSession.created_at.desc())
            .limit(limit)
        )
    )


def get_negotiation(session_db: Session, session_id: str) -> NegotiationSession:
    negotiation = session_db.get(NegotiationSession, session_id)
    if negotiation is None:
        raise EnishiError(
            code="NEGOTIATION_NOT_FOUND",
            message="交渉セッションが見つかりません。",
            status_code=404,
            details={"session_id": session_id},
        )
    return negotiation


def list_agreements(
    session_db: Session,
    *,
    status: str | None = None,
    intent: str | None = None,
) -> list[Agreement]:
    query = select(Agreement).order_by(Agreement.agreed_at.desc())
    if status is not None:
        query = query.where(Agreement.status == status)
    if intent is not None:
        query = query.where(Agreement.intent == intent)
    return list(session_db.scalars(query))


def get_agreement(session_db: Session, agreement_id: str) -> Agreement:
    agreement = session_db.get(Agreement, agreement_id)
    if agreement is None:
        raise EnishiError(
            code="AGREEMENT_NOT_FOUND",
            message="合意が見つかりません。",
            status_code=404,
            details={"agreement_id": agreement_id},
        )
    return agreement


def patch_agreement_status(
    session_db: Session, agreement_id: str, status: str
) -> Agreement:
    agreement = get_agreement(session_db, agreement_id)
    if status not in {item.value for item in AgreementStatus}:
        raise EnishiError(
            code="INVALID_STATE_TRANSITION",
            message="不正な合意ステータスです。",
            status_code=409,
            details={"status": status},
        )
    agreement.status = status
    session_db.commit()
    session_db.refresh(agreement)
    log_event(
        session_db,
        event_type="agreement_status_changed",
        payload={"agreement_id": agreement.id, "intent": agreement.intent, "status": status},
    )
    return agreement


def on_approval_resolved(session_db: Session, approval: Approval) -> None:
    """交渉承認の解決をACCEPT/REJECTへ反映する（enishi.md 方針修正 §4, §31）。"""
    if approval.action_type != "negotiation_decision":
        return
    session_id = str(approval.payload.get("session_id", ""))
    negotiation = session_db.get(NegotiationSession, session_id)
    if negotiation is None or negotiation.pending_approval_id != approval.id:
        return
    if negotiation.status != NegotiationStatus.WAITING_APPROVAL.value:
        return

    last_sequence = (
        session_db.scalars(
            select(NegotiationMessage.sequence)
            .where(NegotiationMessage.session_id == negotiation.id)
            .order_by(NegotiationMessage.sequence.desc())
        ).first()
        or 0
    )
    message_type = (
        MessageType.ACCEPT.value
        if approval.status == ApprovalStatus.APPROVED.value
        else MessageType.REJECT.value
    )
    delta: dict[str, Any]
    message_payload: dict[str, Any] = {}
    if approval.status == ApprovalStatus.APPROVED.value:
        accepted = dict(approval.payload.get("payload", {}))
        delta = {"accepted_task": accepted, "approval_id": approval.id}
        negotiation.status = NegotiationStatus.AGREED.value
        negotiation.result = {"accepted_task": accepted, "approval_id": approval.id}
        _create_agreement(session_db, negotiation, accepted)
    else:
        code = (
            "APPROVAL_EXPIRED"
            if approval.status == ApprovalStatus.EXPIRED.value
            else "APPROVAL_REJECTED"
        )
        delta = {"code": code, "approval_id": approval.id}
        message_payload = {
            "public_reason": to_public_reason(
                ["approval_expired" if code == "APPROVAL_EXPIRED" else "human_rejected"]
            )
        }
        negotiation.status = NegotiationStatus.FAILED.value
        negotiation.result = {"code": code, "approval_id": approval.id}

    session_db.add(
        NegotiationMessage(
            session_id=negotiation.id,
            sequence=last_sequence + 1,
            sender_agent_id=negotiation.responder_clone_id,
            receiver_agent_id=negotiation.initiator_clone_id,
            message_type=message_type,
            intent=negotiation.intent,
            payload=message_payload,
            delta=delta,
            requires_human_approval=True,
        )
    )
    negotiation.pending_approval_id = None
    session_db.commit()


def list_messages(session_db: Session, session_id: str) -> list[NegotiationMessage]:
    from sqlalchemy import select

    get_negotiation(session_db, session_id)
    return list(
        session_db.scalars(
            select(NegotiationMessage)
            .where(NegotiationMessage.session_id == session_id)
            .order_by(NegotiationMessage.sequence)
        )
    )
