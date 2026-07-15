"""監査ログサービス（enishi.md §32）。

payloadにはAPIキーや記憶本文全体など機微情報を入れない前提とする。
呼び出し側はイベントに必要な最小限の情報だけをpayloadへ渡すこと。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from enishi_core.models import AuditLog


def log_event(
    session: Session,
    event_type: str,
    user_id: str | None = None,
    clone_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        event_type=event_type,
        user_id=user_id,
        clone_id=clone_id,
        payload=payload or {},
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def list_events(session: Session, user_id: str | None = None) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    return list(session.scalars(query))
