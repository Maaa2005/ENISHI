"""交渉モデル（enishi.md §25, §27）。"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from enishi_core.models.base import Base, new_id, utc_now


class NegotiationStatus(enum.StrEnum):
    OPEN = "open"
    WAITING_APPROVAL = "waiting_approval"
    AGREED = "agreed"
    FAILED = "failed"


class MessageType(enum.StrEnum):
    REQUEST = "REQUEST"
    PROPOSE = "PROPOSE"
    COUNTER = "COUNTER"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    APPROVAL_RESULT = "APPROVAL_RESULT"
    EXECUTE = "EXECUTE"
    RECEIPT = "RECEIPT"
    ERROR = "ERROR"


class NegotiationSession(Base):
    __tablename__ = "negotiation_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    initiator_clone_id: Mapped[str] = mapped_column(String(32), index=True)
    responder_clone_id: Mapped[str] = mapped_column(String(32), index=True)
    # clone_idは互換のため残し、通信主体の恒久IDをadditiveに保持する。
    initiator_agent_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    responder_agent_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    intent: Mapped[str] = mapped_column(String(100))
    topic: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(16), default=NegotiationStatus.OPEN.value, index=True
    )
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pending_approval_id: Mapped[str | None] = mapped_column(
        ForeignKey("approvals.id"), nullable=True, index=True
    )

    # Relay経由の別所有者ノード交渉用（enishi.md §25 v2, §26）
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    remote_peer_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class AgreementStatus(enum.StrEnum):
    ACTIVE = "active"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class Agreement(Base):
    """ACCEPTで終端した合意内容（enishi.md 方針修正 §4, enishi.md §25）。"""

    __tablename__ = "agreements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("negotiation_sessions.id"), unique=True, index=True
    )
    intent: Mapped[str] = mapped_column(String(100), index=True)
    initiator_agent_id: Mapped[str] = mapped_column(String(64), index=True)
    responder_agent_id: Mapped[str] = mapped_column(String(64), index=True)
    agreed_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), default=AgreementStatus.ACTIVE.value, index=True
    )
    agreed_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class NegotiationMessage(Base):
    __tablename__ = "negotiation_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("negotiation_sessions.id"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    sender_agent_id: Mapped[str] = mapped_column(String(32))
    receiver_agent_id: Mapped[str] = mapped_column(String(32))
    message_type: Mapped[str] = mapped_column(String(32))
    intent: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    delta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class NegotiationDecision(Base):
    """本人エージェントが下した交渉判断の公開可能な根拠。"""

    __tablename__ = "negotiation_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("negotiation_sessions.id"), index=True
    )
    clone_id: Mapped[str] = mapped_column(ForeignKey("clone_agents.id"), index=True)
    policy_version: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class RelayOutbox(Base):
    """Relay停止中も人間の決定を失わない署名済み送信キュー。"""

    __tablename__ = "relay_outbox"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("negotiation_sessions.id"), index=True
    )
    approval_id: Mapped[str | None] = mapped_column(
        ForeignKey("approvals.id"), nullable=True, unique=True, index=True
    )
    envelope: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
