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


_PUBLIC_PAYLOAD_KEYS = {
    "action_type",
    "agent_id",
    "agreement_id",
    "allowed_memory_types",
    "approval_id",
    "code",
    "conflicts",
    "context_tokens",
    "failure_code",
    "fingerprint",
    "has_project",
    "intent",
    "max_sensitivity",
    "memory_count",
    "memory_id",
    "message_count",
    "message_id",
    "outdated_clone_ids",
    "peer_agent_id",
    "processed",
    "project_id",
    "provider",
    "repository_type",
    "rounds",
    "session_id",
    "share_schedule",
    "share_skills",
    "status",
    "task_id",
}


def public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """UIへ公開してよい監査メタデータだけを返す。"""
    return {key: value for key, value in payload.items() if key in _PUBLIC_PAYLOAD_KEYS}


def list_events(
    session: Session, user_id: str | None = None, limit: int | None = None
) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query))
