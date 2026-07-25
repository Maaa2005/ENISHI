"""仕事依頼ドメイン（enishi.md 方針修正 §4）。

単発のポリシー判定（自動承諾／自動カウンター／要承認）で処理する。
"""

from dataclasses import dataclass, field
from datetime import UTC, date, timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from enishi_core.domains.base import BaseDecisionDomain, DomainRequest, NegotiationRequestLike
from enishi_core.domains.common import (
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
from enishi_core.models.base import utc_now
from enishi_core.services.policies import delegation_enabled
from enishi_core.services.public_reasons import to_public_reason

INTENT_TASK_REQUEST = "task.request"


class TaskRequestPayload(BaseModel):
    """`task.request` の payload（Phase B: ドメイン語彙はここへ閉じ込める）。"""

    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    estimated_hours: float | None = Field(default=None, ge=0.0)
    conditions: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class TaskRequestRequest:
    initiator_user_id: str
    responder_user_id: str
    title: str
    description: str = ""
    deadline: str | None = None
    estimated_hours: float | None = None
    conditions: dict[str, Any] = field(default_factory=dict)


class TaskRequestDomain(BaseDecisionDomain):
    """仕事依頼ドメイン（単発のポリシー判定）。"""

    intent = INTENT_TASK_REQUEST
    delegation_key: str | None = "task_negotiation"
    payload_model = TaskRequestPayload

    def validate_request(self, body: NegotiationRequestLike) -> DomainRequest:
        try:
            payload = TaskRequestPayload.model_validate(body.payload)
        except ValidationError as exc:
            raise EnishiError(
                code="INVALID_NEGOTIATION_PAYLOAD",
                message="task.request には title が必要です。",
                status_code=422,
                details={"field": "title"},
            ) from exc
        return TaskRequestRequest(
            initiator_user_id=body.initiator_user_id,
            responder_user_id=body.responder_user_id,
            title=payload.title,
            description=payload.description,
            deadline=payload.deadline,
            estimated_hours=payload.estimated_hours,
            conditions=payload.conditions,
        )

    def topic_of(self, request: DomainRequest) -> str:
        assert isinstance(request, TaskRequestRequest)
        return request.title

    def start(self, session_db: Session, request: DomainRequest) -> NegotiationSession:
        assert isinstance(request, TaskRequestRequest)
        return run_task_request_negotiation(
            session_db,
            initiator_user_id=request.initiator_user_id,
            responder_user_id=request.responder_user_id,
            title=request.title,
            description=request.description,
            deadline=request.deadline,
            estimated_hours=request.estimated_hours,
            conditions=request.conditions,
        )


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
    initiator = require_active_clone(session_db, initiator_user_id)
    responder = require_active_clone(session_db, responder_user_id)
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
        create_negotiation_approval(
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
        create_agreement(session_db, negotiation, accepted)
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
                "public_reason": to_public_reason(["task_request_policy_threshold_exceeded"])
            },
            delta={"proposed_task": counter},
        )
        session_db.add(message)
        negotiation.result = {"proposed_task": counter, "rounds": 1}
        session_db.commit()
        session_db.refresh(negotiation)
        return negotiation

    create_negotiation_approval(
        session_db,
        responder,
        negotiation,
        task_payload,
        reason="task_request_policy_threshold_exceeded",
    )
    return negotiation
