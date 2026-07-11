"""ローカルプロジェクトモデル（twinlink.md §24）。"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from twinlink_core.models.base import Base, new_id, utc_now

DEFAULT_PROJECT_PERMISSIONS: dict[str, bool] = {
    "read": True,
    "create": True,
    "modify": True,
    "delete": False,
    "run_commands": True,
    "use_network": False,
    "git_commit": False,
    "git_push": False,
}


def _default_permissions() -> dict[str, bool]:
    return dict(DEFAULT_PROJECT_PERMISSIONS)


class LocalProject(Base):
    __tablename__ = "local_projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    root_path: Mapped[str] = mapped_column(String(1000))
    repository_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    trusted: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON, default=_default_permissions)

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    last_opened_at: Mapped[datetime | None] = mapped_column(nullable=True)
