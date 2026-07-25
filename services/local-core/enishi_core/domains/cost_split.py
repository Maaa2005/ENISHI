"""割り勘ドメイン（Phase B）。

複数人で発生した費用の分担額の合意を、決定的な譲歩ロジックで交渉する（LLM不使用）。
支払いの実行・外部決済連携は一切行わない（合意の生成まで）。

既存2ドメインは離散候補集合の交差（meeting）と閾値比較（task）という二値判定だったのに対し、
`cost.split` は連続値の譲歩（効用の理想点と留保価格の間で歩み寄る）という第三の型を実例にする。

最小情報の原則: responder は自分の予算・留保価格・効用パラメータを一切メッセージに載せない。
送ってよいのは対案の金額（`proposed_share`）と `public_reason` だけ。
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from enishi_core.domains.base import BaseDecisionDomain, DomainRequest, NegotiationRequestLike
from enishi_core.domains.common import (
    append_message,
    create_agreement,
    create_negotiation_approval,
    require_active_clone,
)
from enishi_core.errors import EnishiError
from enishi_core.models import (
    CloneAgent,
    MessageType,
    NegotiationMessage,
    NegotiationSession,
    NegotiationStatus,
)
from enishi_core.services.policies import approval_required, delegation_enabled
from enishi_core.services.public_reasons import to_public_reason

INTENT_COST_SPLIT = "cost.split"
_MAX_ROUNDS = 3


class CostSplitPayload(BaseModel):
    """`cost.split` の payload（initiator が送る依頼）。"""

    title: str = Field(min_length=1, max_length=500)
    total_amount: float = Field(gt=0)
    currency: str = Field(default="JPY", min_length=3, max_length=3)
    proposed_share: float = Field(ge=0)
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def validate_share_within_total(self) -> "CostSplitPayload":
        if self.proposed_share > self.total_amount:
            raise ValueError("proposed_share must not exceed total_amount")
        return self


@dataclass(frozen=True)
class CostSplitRequest:
    initiator_user_id: str
    responder_user_id: str
    title: str
    total_amount: float
    currency: str
    proposed_share: float
    deadline: str | None = None


class CostSplitDomain(BaseDecisionDomain):
    """割り勘ドメイン（連続値の譲歩）。"""

    intent = INTENT_COST_SPLIT
    delegation_key: str | None = "cost_split_negotiation"
    payload_model = CostSplitPayload

    def validate_request(self, body: NegotiationRequestLike) -> DomainRequest:
        try:
            payload = CostSplitPayload.model_validate(body.payload)
        except ValidationError as exc:
            raise EnishiError(
                code="INVALID_NEGOTIATION_PAYLOAD",
                message=(
                    "cost.split には title, total_amount, proposed_share が必要です"
                    "（proposed_share は total_amount 以下）。"
                ),
                status_code=422,
                details={"intent": body.intent},
            ) from exc
        return CostSplitRequest(
            initiator_user_id=body.initiator_user_id,
            responder_user_id=body.responder_user_id,
            title=payload.title,
            total_amount=payload.total_amount,
            currency=payload.currency,
            proposed_share=payload.proposed_share,
            deadline=payload.deadline,
        )

    def topic_of(self, request: DomainRequest) -> str:
        assert isinstance(request, CostSplitRequest)
        return request.title

    def start(self, session_db: Session, request: DomainRequest) -> NegotiationSession:
        assert isinstance(request, CostSplitRequest)
        return run_cost_split_negotiation(
            session_db,
            initiator_user_id=request.initiator_user_id,
            responder_user_id=request.responder_user_id,
            title=request.title,
            total_amount=request.total_amount,
            currency=request.currency,
            proposed_share=request.proposed_share,
            deadline=request.deadline,
        )


def _cost_split_policy(clone: CloneAgent) -> dict[str, Any]:
    raw = clone.policy_profile.get("cost_split", {})
    policy = raw if isinstance(raw, dict) else {}
    return {
        "max_auto_accept_amount": float(policy.get("max_auto_accept_amount", 5000.0)),
        "max_negotiable_amount": float(policy.get("max_negotiable_amount", 30000.0)),
        "reservation_ratio": float(policy.get("reservation_ratio", 0.5)),
        "concession_ratio": float(policy.get("concession_ratio", 0.5)),
    }


def _cost_split_preferred_ratio(clone: CloneAgent) -> float:
    raw = clone.preference_profile.get("cost_split", {})
    preference = raw if isinstance(raw, dict) else {}
    return float(preference.get("preferred_ratio", 0.5))


def _agreed_payload(
    *,
    title: str,
    total_amount: float,
    currency: str,
    agreed_share: float,
    deadline: str | None,
) -> dict[str, Any]:
    return {
        "intent": INTENT_COST_SPLIT,
        "title": title,
        "total_amount": total_amount,
        "currency": currency,
        "agreed_share": agreed_share,
        "deadline": deadline,
    }


def run_cost_split_negotiation(
    session_db: Session,
    initiator_user_id: str,
    responder_user_id: str,
    title: str,
    total_amount: float,
    currency: str,
    proposed_share: float,
    deadline: str | None = None,
) -> NegotiationSession:
    """割り勘の分担額を決定的に交渉する（連続値の譲歩、LLM不使用）。"""
    initiator = require_active_clone(session_db, initiator_user_id)
    responder = require_active_clone(session_db, responder_user_id)

    request_payload: dict[str, Any] = {
        "intent": INTENT_COST_SPLIT,
        "title": title,
        "total_amount": total_amount,
        "currency": currency,
        "proposed_share": proposed_share,
        "deadline": deadline,
    }

    negotiation = NegotiationSession(
        initiator_clone_id=initiator.id,
        responder_clone_id=responder.id,
        intent=INTENT_COST_SPLIT,
        topic=title,
    )
    session_db.add(negotiation)
    session_db.flush()

    messages: list[NegotiationMessage] = []

    def add_message(
        sender: CloneAgent,
        receiver: CloneAgent,
        message_type: MessageType,
        payload: dict[str, Any] | None = None,
        delta: dict[str, Any] | None = None,
    ) -> NegotiationMessage:
        return append_message(
            session_db,
            negotiation,
            messages,
            sender=sender,
            receiver=receiver,
            message_type=message_type,
            intent=INTENT_COST_SPLIT,
            payload=payload,
            delta=delta,
        )

    add_message(initiator, responder, MessageType.REQUEST, payload=request_payload)

    policy = _cost_split_policy(responder)
    max_auto_accept_amount = policy["max_auto_accept_amount"]
    max_negotiable_amount = policy["max_negotiable_amount"]
    reservation_ratio = policy["reservation_ratio"]
    concession_ratio = policy["concession_ratio"]
    preferred_ratio = min(_cost_split_preferred_ratio(responder), reservation_ratio)

    offer = round(proposed_share, 2)
    reservation = round(total_amount * reservation_ratio, 2)
    current = round(total_amount * preferred_ratio, 2)

    # 事前ガード（全ドメイン共通・enishi_core.services.decision_evaluator.evaluate_common_guards）
    # 委任OFF / confidence閾値未満 / relationship が承認要求 -> 承認エスカレーション。
    # ローカル交渉には relay 経由の相手 personal agent id が無いため、
    # 関係性ポリシーの照合キーには initiator のクローンIDを代用する。
    from enishi_core.services.decision_evaluator import evaluate_common_guards

    delegation_ok = delegation_enabled(
        session_db, responder.user_id, "cost_split_negotiation", default=True
    )
    guard = evaluate_common_guards(
        clone=responder,
        delegation_enabled=delegation_ok,
        peer_personal_agent_id=initiator.id,
        not_delegated_reason_code="cost_split_negotiation_not_delegated",
    )
    guard_reason_codes = [*guard.pre_reason_codes, *guard.post_reason_codes]
    if guard_reason_codes:
        create_negotiation_approval(
            session_db,
            responder,
            negotiation,
            _agreed_payload(
                title=title,
                total_amount=total_amount,
                currency=currency,
                agreed_share=offer,
                deadline=deadline,
            ),
            reason=guard_reason_codes[0],
        )
        return negotiation

    if offer <= max_auto_accept_amount:
        add_message(responder, initiator, MessageType.ACCEPT, delta={"agreed_share": offer})
        negotiation.status = NegotiationStatus.AGREED.value
        negotiation.result = {"agreed_share": offer, "rounds": 1}
        create_agreement(
            session_db,
            negotiation,
            _agreed_payload(
                title=title,
                total_amount=total_amount,
                currency=currency,
                agreed_share=offer,
                deadline=deadline,
            ),
        )
        session_db.commit()
        session_db.refresh(negotiation)
        return negotiation

    rounds = 0
    for round_number in range(1, _MAX_ROUNDS + 1):
        rounds = round_number
        if offer <= current:
            add_message(responder, initiator, MessageType.ACCEPT, delta={"agreed_share": offer})
            negotiation.status = NegotiationStatus.AGREED.value
            negotiation.result = {"agreed_share": offer, "rounds": rounds}
            create_agreement(
                session_db,
                negotiation,
                _agreed_payload(
                    title=title,
                    total_amount=total_amount,
                    currency=currency,
                    agreed_share=offer,
                    deadline=deadline,
                ),
            )
            session_db.commit()
            session_db.refresh(negotiation)
            return negotiation

        if offer > reservation:
            if offer <= max_negotiable_amount or approval_required(
                session_db, responder.user_id, "high_value"
            ):
                create_negotiation_approval(
                    session_db,
                    responder,
                    negotiation,
                    _agreed_payload(
                        title=title,
                        total_amount=total_amount,
                        currency=currency,
                        agreed_share=offer,
                        deadline=deadline,
                    ),
                    reason="cost_share_exceeds_reservation",
                )
                return negotiation

            add_message(
                responder,
                initiator,
                MessageType.REJECT,
                payload={"public_reason": to_public_reason(["cost_share_exceeds_limit"])},
                delta={"code": "COST_SHARE_EXCEEDS_LIMIT"},
            )
            negotiation.status = NegotiationStatus.FAILED.value
            negotiation.result = {"code": "COST_SHARE_EXCEEDS_LIMIT", "rounds": rounds}
            session_db.commit()
            session_db.refresh(negotiation)
            return negotiation

        current = round(min(reservation, current + (offer - current) * concession_ratio), 2)

        if round_number == _MAX_ROUNDS:
            add_message(responder, initiator, MessageType.ACCEPT, delta={"agreed_share": offer})
            negotiation.status = NegotiationStatus.AGREED.value
            negotiation.result = {"agreed_share": offer, "rounds": rounds}
            create_agreement(
                session_db,
                negotiation,
                _agreed_payload(
                    title=title,
                    total_amount=total_amount,
                    currency=currency,
                    agreed_share=offer,
                    deadline=deadline,
                ),
            )
            session_db.commit()
            session_db.refresh(negotiation)
            return negotiation

        add_message(
            responder,
            initiator,
            MessageType.COUNTER,
            payload={"public_reason": to_public_reason(["cost_split_concession"])},
            delta={"proposed_share": current},
        )

    session_db.commit()
    session_db.refresh(negotiation)
    return negotiation
