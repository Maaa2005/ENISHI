"""リプレイ防止（twinlink.md §25 信頼モデル v2）。

検証済みのmessage_idをTTL付きで記録し、重複受信を拒否する。
"""

from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from twinlink_core.errors import TwinLinkError
from twinlink_core.models import SeenMessage
from twinlink_core.models.base import utc_now


def check_and_record(session: Session, message_id: str, ttl_seconds: int = 3600) -> None:
    """message_idが既知ならリプレイとして拒否し、未知なら記録する。

    期限切れの記録はこの関数内で遅延削除する。
    """
    now = utc_now()
    session.execute(delete(SeenMessage).where(SeenMessage.expires_at < now))

    if session.get(SeenMessage, message_id) is not None:
        session.commit()
        raise TwinLinkError(
            code="MESSAGE_REPLAYED",
            message="同一message_idのメッセージを既に受信しています。",
            status_code=409,
            details={"message_id": message_id},
        )

    session.add(SeenMessage(message_id=message_id, expires_at=now + timedelta(seconds=ttl_seconds)))
    session.commit()
