"""全ドメイン共通の交渉部品（enishi.md §25, §27, §28, §31）。

「多ラウンド提案・逆提案」（meeting）と「単発のポリシー判定」（task）は構造が異なるため、
無理に1つの状態機械へは統合しない。ここに置くのは、どちらの構造でも共通して使う
部品（アクティブクローンの取得、合意の保存、承認の作成、メッセージの採番）だけ。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from enishi_core.errors import EnishiError
from enishi_core.models import (
    Agreement,
    Approval,
    CloneAgent,
    MessageType,
    NegotiationMessage,
    NegotiationSession,
    NegotiationStatus,
)
from enishi_core.services import approvals as approval_service
from enishi_core.services.audit import log_event


def require_active_clone(session_db: Session, user_id: str) -> CloneAgent:
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


def create_agreement(
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


def create_negotiation_approval(
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


def append_message(
    session_db: Session,
    negotiation: NegotiationSession,
    messages: list[NegotiationMessage],
    *,
    sender: CloneAgent,
    receiver: CloneAgent,
    message_type: MessageType,
    intent: str,
    payload: dict[str, Any] | None = None,
    delta: dict[str, Any] | None = None,
    requires_human_approval: bool = False,
) -> NegotiationMessage:
    """sequence採番つきで `NegotiationMessage` を積む（1始まり・呼び出し順）。"""
    message = NegotiationMessage(
        session_id=negotiation.id,
        sequence=len(messages) + 1,
        sender_agent_id=sender.id,
        receiver_agent_id=receiver.id,
        message_type=message_type.value,
        intent=intent,
        payload=payload or {},
        delta=delta or {},
        requires_human_approval=requires_human_approval,
    )
    session_db.add(message)
    messages.append(message)
    return message
