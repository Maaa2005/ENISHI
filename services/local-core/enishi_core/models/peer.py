"""ピアエージェントモデル（enishi.md §25 信頼モデル v2）。

初回ペアリングはユーザー承認付きの公開鍵フィンガープリント交換とする。
"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from enishi_core.models.base import Base, utc_now


class PeerStatus(enum.StrEnum):
    PENDING = "pending"
    TRUSTED = "trusted"
    BLOCKED = "blocked"


class PeerAgent(Base):
    __tablename__ = "peer_agents"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    public_key: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64))
    # 既存agent_idは端末ノードIDとして維持する。未設定の旧行は
    # personal_agent_id == agent_id とみなして後方互換を保つ。
    personal_agent_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default=PeerStatus.PENDING.value, index=True)

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class PeerDisclosurePolicy(Base):
    """相手別の情報公開設定（enishi.md 方針修正 §4, enishi.md §17）。"""

    __tablename__ = "peer_disclosure_policies"

    peer_agent_id: Mapped[str] = mapped_column(
        ForeignKey("peer_agents.agent_id"), primary_key=True
    )
    allowed_memory_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_sensitivity: Mapped[str] = mapped_column(String(16), default="internal")
    share_schedule: Mapped[bool] = mapped_column(Boolean, default=True)
    share_skills: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class DefaultDisclosurePolicy(Base):
    """相手別ポリシー未設定時の既定公開設定。"""

    __tablename__ = "default_disclosure_policy"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    allowed_memory_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_sensitivity: Mapped[str] = mapped_column(String(16), default="internal")
    share_schedule: Mapped[bool] = mapped_column(Boolean, default=True)
    share_skills: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)
