"""クローン実行用コンテキストパッケージモデル（enishi.md §20）。"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from enishi_core.models.base import Base, new_id, utc_now


class CloneContextPackage(Base):
    __tablename__ = "clone_context_packages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    clone_id: Mapped[str] = mapped_column(String(32), index=True)
    clone_version: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_goal: Mapped[str] = mapped_column(String(2000))

    relevant_preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    relevant_skills: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    relevant_project_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    relevant_decisions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    coding_rules: Mapped[list[Any]] = mapped_column(JSON, default=list)
    prohibited_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    approval_requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    file_references: Mapped[list[str]] = mapped_column(JSON, default=list)

    estimated_tokens: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(default=utc_now)
