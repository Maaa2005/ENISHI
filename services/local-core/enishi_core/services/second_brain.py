"""UIを起動せず利用できるENISHI内蔵セカンドブレイン。"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from enishi_core.models import MemoryItem, MemorySensitivity, MemoryStatus, User
from enishi_core.services import memory_router


def ensure_local_user(session: Session, preferred_id: str | None = None) -> User:
    user = session.get(User, preferred_id) if preferred_id else session.scalar(
        select(User).order_by(User.created_at)
    )
    if user is None:
        user = User(display_name="ENISHI User")
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


def search(session: Session, *, user_id: str, query: str, limit: int = 10) -> list[MemoryItem]:
    memory_router.refresh_external_index(session, user_id=user_id)
    term = f"%{query.strip()}%"
    statement = (
        select(MemoryItem)
        .where(
            MemoryItem.user_id == user_id,
            MemoryItem.status == MemoryStatus.ACTIVE.value,
            MemoryItem.sensitivity != MemorySensitivity.SECRET.value,
            or_(MemoryItem.title.ilike(term), MemoryItem.searchable_text.ilike(term)),
        )
        .order_by(MemoryItem.updated_at.desc())
        .limit(max(1, min(limit, 50)))
    )
    return list(session.scalars(statement))


def remember(
    session: Session,
    *,
    user_id: str,
    title: str,
    text: str,
    memory_type: str = "episodic",
    sensitivity: str = "private",
    tags: list[str] | None = None,
) -> MemoryItem:
    return memory_router.remember(
        session,
        user_id=user_id,
        title=title[:200],
        text=text,
        memory_type=memory_type,
        sensitivity=sensitivity,
        tags=tags or ["second-brain"],
    )
