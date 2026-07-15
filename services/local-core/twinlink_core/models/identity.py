"""本人エージェントと端末ノードの分離モデル。"""

from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from twinlink_core.models.base import Base, new_id, utc_now


def new_personal_agent_id() -> str:
    """端末鍵に依存しない恒久的な本人エージェントIDを生成する。"""
    return f"pa_{new_id()}"


class PersonalAgent(Base):
    __tablename__ = "personal_agents"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=new_personal_agent_id
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    active_clone_id: Mapped[str | None] = mapped_column(
        ForeignKey("clone_agents.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class DeviceNode(Base):
    __tablename__ = "device_nodes"
    __table_args__ = (
        UniqueConstraint("personal_agent_id", "node_id", name="uq_device_personal_node"),
    )

    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    personal_agent_id: Mapped[str] = mapped_column(
        ForeignKey("personal_agents.id"), nullable=False, index=True
    )
    public_key: Mapped[str] = mapped_column(String(200), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)
