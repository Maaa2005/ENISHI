"""記憶サービス（twinlink.md §17）。

sensitivity=secretの記憶はLLM/外部へ渡すコンテキストに含めない。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from twinlink_core.errors import TwinLinkError
from twinlink_core.models import (
    CloneAgent,
    CloneStatus,
    MemoryItem,
    MemorySensitivity,
    MemorySnapshot,
    MemoryStatus,
)
from twinlink_core.models.base import utc_now
from twinlink_core.services.audit import log_event


def create_memory(
    session: Session,
    *,
    user_id: str,
    source_type: str,
    source_reference: str | None,
    memory_type: str,
    title: str,
    content: dict[str, Any],
    searchable_text: str | None,
    confidence: float,
    sensitivity: str,
    relevance_tags: list[str],
    effective_from: datetime | None = None,
    effective_until: datetime | None = None,
) -> MemoryItem:
    memory = MemoryItem(
        user_id=user_id,
        source_type=source_type,
        source_reference=source_reference,
        memory_type=memory_type,
        title=title,
        content=content,
        searchable_text=searchable_text,
        confidence=confidence,
        sensitivity=sensitivity,
        relevance_tags=relevance_tags,
        effective_from=effective_from,
        effective_until=effective_until,
    )
    session.add(memory)
    session.commit()
    session.refresh(memory)
    return memory


def list_memories(session: Session, user_id: str) -> list[MemoryItem]:
    return list(
        session.scalars(
            select(MemoryItem)
            .where(
                MemoryItem.user_id == user_id,
                MemoryItem.status != MemoryStatus.DELETED.value,
            )
            .order_by(MemoryItem.created_at.desc())
        )
    )


def _mark_clones_outdated_for_memory(session: Session, memory: MemoryItem) -> list[str]:
    snapshots = list(
        session.scalars(
            select(MemorySnapshot).where(MemorySnapshot.user_id == memory.user_id)
        )
    )
    snapshot_ids = [
        snapshot.id for snapshot in snapshots if memory.id in set(snapshot.memory_ids)
    ]
    if not snapshot_ids:
        return []
    clones = list(
        session.scalars(
            select(CloneAgent).where(
                CloneAgent.user_id == memory.user_id,
                CloneAgent.status == CloneStatus.ACTIVE.value,
                CloneAgent.memory_snapshot_id.in_(snapshot_ids),
            )
        )
    )
    for clone in clones:
        clone.status = CloneStatus.OUTDATED.value
    return [clone.id for clone in clones]


def delete_memory(session: Session, memory_id: str) -> MemoryItem:
    """論理削除し、使用中activeクローンをoutdatedにする（twinlink.md §17）。"""
    memory = session.get(MemoryItem, memory_id)
    if memory is None:
        raise TwinLinkError(
            code="MEMORY_PERMISSION_DENIED",
            message="記憶が見つかりません。",
            status_code=404,
            details={"memory_id": memory_id},
        )
    memory.status = MemoryStatus.DELETED.value
    memory.updated_at = utc_now()
    outdated_clone_ids = _mark_clones_outdated_for_memory(session, memory)
    session.commit()
    session.refresh(memory)
    log_event(
        session,
        event_type="memory_deleted",
        user_id=memory.user_id,
        payload={"memory_id": memory.id, "outdated_clone_ids": outdated_clone_ids},
    )
    return memory


def update_memory(
    session: Session,
    memory_id: str,
    *,
    content: dict[str, Any] | None = None,
    sensitivity: str | None = None,
) -> MemoryItem:
    """content/sensitivityの大幅更新時に関連activeクローンをoutdatedにする。"""
    memory = session.get(MemoryItem, memory_id)
    if memory is None:
        raise TwinLinkError(
            code="MEMORY_PERMISSION_DENIED",
            message="記憶が見つかりません。",
            status_code=404,
            details={"memory_id": memory_id},
        )

    changed = False
    if content is not None and content != memory.content:
        memory.content = content
        changed = True
    if sensitivity is not None and sensitivity != memory.sensitivity:
        memory.sensitivity = sensitivity
        changed = True
    if changed:
        memory.updated_at = utc_now()
        outdated_clone_ids = _mark_clones_outdated_for_memory(session, memory)
        session.commit()
        session.refresh(memory)
        log_event(
            session,
            event_type="memory_updated",
            user_id=memory.user_id,
            payload={"memory_id": memory.id, "outdated_clone_ids": outdated_clone_ids},
        )
        return memory
    session.refresh(memory)
    return memory


def exportable_memories(session: Session, user_id: str) -> list[MemoryItem]:
    """LLM/外部へ渡してよい記憶だけを返す。

    sensitivity=secretの記憶と、status=activeでない記憶、
    effective_untilを過ぎた記憶を除外する。
    """
    now = utc_now()
    candidates = session.scalars(
        select(MemoryItem).where(
            MemoryItem.user_id == user_id,
            MemoryItem.status == MemoryStatus.ACTIVE.value,
            MemoryItem.sensitivity != MemorySensitivity.SECRET.value,
        )
    )
    return [m for m in candidates if m.effective_until is None or m.effective_until > now]
