"""ピアエージェントモデル（twinlink.md §25 信頼モデル v2）。

初回ペアリングはユーザー承認付きの公開鍵フィンガープリント交換とする。
"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from twinlink_core.models.base import Base, utc_now


class PeerStatus(enum.StrEnum):
    PENDING = "pending"
    TRUSTED = "trusted"
    BLOCKED = "blocked"


class PeerAgent(Base):
    __tablename__ = "peer_agents"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    public_key: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=PeerStatus.PENDING.value, index=True)

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class PeerDisclosurePolicy(Base):
    """相手別の情報公開設定（twinlink.md 方針修正 §4, twinlink.md §17）。"""

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
