"""クローンエージェントモデル（twinlink.md §18）。"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from twinlink_core.models.base import Base, new_id, utc_now


class CloneStatus(enum.StrEnum):
    DRAFT = "draft"
    REVIEW_REQUIRED = "review_required"
    ACTIVE = "active"
    PAUSED = "paused"
    OUTDATED = "outdated"
    DELETED = "deleted"


class CloneAgent(Base):
    __tablename__ = "clone_agents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default=CloneStatus.REVIEW_REQUIRED.value)

    identity_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    preference_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    skill_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    coding_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    project_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    policy_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    communication_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    memory_snapshot_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    activated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class MemorySnapshot(Base):
    __tablename__ = "memory_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    memory_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
