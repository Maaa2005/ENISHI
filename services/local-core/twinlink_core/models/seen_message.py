"""受信済みメッセージID記録モデル（twinlink.md §25 信頼モデル v2）。

検証済みのmessage_idをTTL付きで保持し、リプレイを拒否する。
"""

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from twinlink_core.models.base import Base


class SeenMessage(Base):
    __tablename__ = "seen_messages"

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column()
