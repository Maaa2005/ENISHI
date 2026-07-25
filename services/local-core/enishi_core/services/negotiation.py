"""構造化交渉（enishi.md §25, §27, §28）。

ドメイン非依存の照会系（一覧・取得・承認解決の反映）だけをここに残す。
交渉そのものの実行ロジックはドメインごとに `enishi_core.domains` 配下へ移した
（`domains/meeting_schedule.py`, `domains/task_request.py`）。
`run_negotiation` / `run_task_request_negotiation` は後方互換の薄いラッパとして残す。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from enishi_core.domains.common import create_agreement
from enishi_core.domains.meeting_schedule import (
    INTENT_MEETING_SCHEDULE,
    build_email_transcript,
)
from enishi_core.domains.meeting_schedule import run_negotiation as _run_meeting_negotiation
from enishi_core.domains.task_request import INTENT_TASK_REQUEST
from enishi_core.domains.task_request import (
    run_task_request_negotiation as _run_task_request_negotiation,
)
from enishi_core.errors import EnishiError
from enishi_core.models import (
    Agreement,
    AgreementStatus,
    Approval,
    ApprovalStatus,
    MessageType,
    NegotiationMessage,
    NegotiationSession,
    NegotiationStatus,
)
from enishi_core.services.audit import log_event
from enishi_core.services.public_reasons import to_public_reason

__all__ = [
    "INTENT_MEETING_SCHEDULE",
    "INTENT_TASK_REQUEST",
    "build_email_transcript",
    "run_negotiation",
    "run_task_request_negotiation",
    "list_negotiations",
    "get_negotiation",
    "list_agreements",
    "get_agreement",
    "patch_agreement_status",
    "on_approval_resolved",
    "list_messages",
]


def run_negotiation(
    session_db: Session,
    initiator_user_id: str,
    responder_user_id: str,
    topic: str,
    duration_minutes: int,
    date_range: dict[str, str],
    preferred_time_ranges: list[dict[str, str]],
) -> NegotiationSession:
    """後方互換ラッパ。実体は domains/meeting_schedule.py。"""
    return _run_meeting_negotiation(
        session_db,
        initiator_user_id,
        responder_user_id,
        topic,
        duration_minutes,
        date_range,
        preferred_time_ranges,
    )


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
    """後方互換ラッパ。実体は domains/task_request.py。"""
    return _run_task_request_negotiation(
        session_db,
        initiator_user_id,
        responder_user_id,
        title,
        description=description,
        deadline=deadline,
        estimated_hours=estimated_hours,
        conditions=conditions,
    )


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
        create_agreement(session_db, negotiation, accepted)
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
