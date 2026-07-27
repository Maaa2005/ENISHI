"""全ドメイン共通の交渉部品（enishi.md §25, §27, §28, §31）。

「多ラウンド提案・逆提案」（meeting）と「単発のポリシー判定」（task）は構造が異なるため、
無理に1つの状態機械へは統合しない。ここに置くのは、どちらの構造でも共通して使う
部品（アクティブクローンの取得、合意の保存、承認の作成、メッセージの採番）だけ。
"""

from dataclasses import dataclass
from typing import Any, Literal

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

DecisionOutcome = Literal["auto_accept", "approval_required", "counter", "reject"]

# E3-c: クローンが active になるのは人間のレビューを通った時点であり、活性化そのものが
# 承認ゲートである（services/clones.py::activate_clone 参照）。よってこの閾値自体は
# 変更しない。記憶削除等で活性化後に confidence が下がったケース（enishi.md §17）で
# 正しく発火させるためのガードとして残す。
CONFIDENCE_THRESHOLD = 0.6


@dataclass(frozen=True)
class DecisionEvaluation:
    """ドメインの終端判断1件分の評価結果。"""

    outcome: DecisionOutcome
    reason_codes: list[str]
    evidence: dict[str, Any]
    confidence: float
    policy_version: int


@dataclass(frozen=True)
class CommonGuardResult:
    """全ドメイン共通のガード判定結果。

    delegation/confidence は判断の先頭に、relationship は末尾に来る（既存の並び順）ため、
    reason_codes を pre/post に分けて呼び出し側でドメイン固有の理由を挟み込めるようにする。
    """

    confidence: float
    pre_reason_codes: list[str]
    post_reason_codes: list[str]
    evidence: dict[str, Any]


def evaluate_common_guards(
    *,
    clone: CloneAgent,
    delegation_enabled: bool,
    peer_personal_agent_id: str,
    not_delegated_reason_code: str,
) -> CommonGuardResult:
    """委任・confidence・関係性という、全ドメイン共通のガードを評価する。

    E3-a: 元は `services/decision_evaluator.py` にあったが、`domains/meeting_schedule.py`
    などドメイン側の評価関数からも参照する必要があるため、循環 import を避けて
    `domains/common.py`（どの構造からも参照できる共通部品置き場）へ移した。
    `services/decision_evaluator.py` はここから再エクスポートして後方互換を保つ。
    """
    confidence = max(0.0, min(1.0, float(clone.confidence_score)))

    pre_reason_codes: list[str] = []
    if not delegation_enabled:
        pre_reason_codes.append(not_delegated_reason_code)
    if confidence < CONFIDENCE_THRESHOLD:
        pre_reason_codes.append("clone_confidence_below_threshold")

    relationship_auto_accept: bool | None = None
    relationships = clone.preference_profile.get("relationships", {})
    if isinstance(relationships, dict):
        relationship = relationships.get(peer_personal_agent_id, {})
        if isinstance(relationship, dict) and isinstance(
            relationship.get("allow_auto_accept"), bool
        ):
            relationship_auto_accept = relationship["allow_auto_accept"]

    post_reason_codes: list[str] = []
    if relationship_auto_accept is False:
        post_reason_codes.append("relationship_requires_approval")

    return CommonGuardResult(
        confidence=confidence,
        pre_reason_codes=pre_reason_codes,
        post_reason_codes=post_reason_codes,
        evidence={
            "delegation_enabled": delegation_enabled,
            "clone_confidence": confidence,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "relationship_auto_accept": relationship_auto_accept,
        },
    )


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
    decider: CloneAgent,
    negotiation: NegotiationSession,
    payload: dict[str, Any],
    reason: str,
    *,
    sequence: int = 2,
) -> Approval:
    """手番のエージェント（`decider`）が自分の所有者へ最終判断をエスカレーションする。

    `meeting.schedule` / `task.request` は常に responder が decider（挙動は変わらない）。
    `cost.split`（Phase D）以降は、交互提示で手番になった側（responder/initiator どちらも
    ありうる）が decider になる。

    `sequence` はデフォルトで2（REQUESTの直後）。`cost.split` のように複数ラウンドの
    COUNTER の後でエスカレーションしうるドメインは、呼び出し側で正しい採番
    （`len(messages) + 1`）を渡すこと。
    """
    other_clone_id = (
        negotiation.initiator_clone_id
        if decider.id == negotiation.responder_clone_id
        else negotiation.responder_clone_id
    )
    approval = approval_service.create_approval(
        session_db,
        user_id=decider.user_id,
        action_type="negotiation_decision",
        description=f"交渉 {negotiation.id} の最終判断が必要です。",
        level=1,
        payload={
            "session_id": negotiation.id,
            "intent": negotiation.intent,
            "reason": reason,
            "proposed_action": "ACCEPT",
            "payload": payload,
            # E2: 解決時にどちらのクローンが送信者になるかを明示する。responder 決め打ちを
            # 外すため（on_approval_resolved 参照）。無ければ従来どおり responder_clone_id
            # にフォールバックする。
            "decider_clone_id": decider.id,
        },
    )
    negotiation.status = NegotiationStatus.WAITING_APPROVAL.value
    negotiation.pending_approval_id = approval.id
    session_db.add(
        NegotiationMessage(
            session_id=negotiation.id,
            sequence=sequence,
            sender_agent_id=decider.id,
            receiver_agent_id=other_clone_id,
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
