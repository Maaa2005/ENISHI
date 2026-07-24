"""記憶モデル（enishi.md §17）。"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from enishi_core.models.base import Base, new_id, utc_now


class MemoryType(enum.StrEnum):
    IDENTITY = "identity"
    PREFERENCE = "preference"
    SKILL = "skill"
    PROJECT = "project"
    PROJECT_STATE = "project_state"
    DECISION = "decision"
    POLICY = "policy"
    COMMUNICATION = "communication"
    ENVIRONMENT = "environment"
    NEGATIVE_PREFERENCE = "negative_preference"
    EPISODIC = "episodic"
    RELATIONSHIP = "relationship"
    SCHEDULE = "schedule"


class MemorySensitivity(enum.StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    RESTRICTED = "restricted"
    SECRET = "secret"


class MemoryStatus(enum.StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class MemoryBackendStatus(enum.StrEnum):
    INTERNAL_PRIMARY = "internal_primary"
    EXTERNAL_PRIMARY = "external_primary"
    EXTERNAL_UNAVAILABLE = "external_unavailable"
    MIGRATING = "migrating"


class MemoryItem(Base):
    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(64))
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)

    memory_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    searchable_text: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    sensitivity: Mapped[str] = mapped_column(
        String(16), default=MemorySensitivity.INTERNAL.value, index=True
    )
    relevance_tags: Mapped[list[str]] = mapped_column(JSON, default=list)

    effective_from: Mapped[datetime | None] = mapped_column(nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(nullable=True)

    status: Mapped[str] = mapped_column(String(16), default=MemoryStatus.ACTIVE.value, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class MemorySourceSetting(Base):
    __tablename__ = "memory_source_settings"

    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    scope: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class MemoryBackendState(Base):
    """ユーザーごとの記憶の正本を保持し、一時切断時のsplit-brainを防ぐ。"""

    __tablename__ = "memory_backend_states"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    primary_source: Mapped[str] = mapped_column(String(64), default="memories")
    primary_scope: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(
        String(32), default=MemoryBackendStatus.INTERNAL_PRIMARY.value, index=True
    )
    detected_automatically: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime] = mapped_column(default=utc_now)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)
