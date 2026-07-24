"""外部脳を優先し、未接続時だけENISHIを正本にする記憶ルーター。"""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from enishi_core.config import get_settings
from enishi_core.errors import EnishiError
from enishi_core.models import (
    MemoryBackendState,
    MemoryBackendStatus,
    MemoryItem,
    MemoryStatus,
)
from enishi_core.models.base import utc_now
from enishi_core.services import external_memory, memories, memory_source_settings

INTERNAL_SOURCE = "memories"
PENDING_SOURCE = "enishi_pending"
EXTERNAL_SOURCES = {"obsidian", "markdown_folder"}
EXTERNAL_CANONICAL_TYPES = {
    "identity",
    "preference",
    "negative_preference",
    "skill",
    "project",
    "decision",
    "policy",
    "communication",
    "environment",
}


def _active_count(
    session: Session, user_id: str, *, sources: set[str], canonical_only: bool = False
) -> int:
    statement = select(func.count()).select_from(MemoryItem).where(
        MemoryItem.user_id == user_id,
        MemoryItem.source_type.in_(sources),
        MemoryItem.status == MemoryStatus.ACTIVE.value,
    )
    if canonical_only:
        statement = statement.where(MemoryItem.memory_type.in_(EXTERNAL_CANONICAL_TYPES))
    return int(session.scalar(statement) or 0)


def _connected_external_setting(session: Session) -> tuple[str, str] | None:
    settings = memory_source_settings.list_settings(session)
    for setting in settings:
        if (
            setting.source in EXTERNAL_SOURCES
            and setting.connected
            and setting.enabled
            and setting.scope
        ):
            return setting.source, setting.scope
    return None


def _auto_detect_external(session: Session) -> tuple[str, str] | None:
    if not get_settings().auto_discover_external_memory:
        return None
    discovered = external_memory.discover_markdown_sources()
    if not discovered:
        return None
    candidate = discovered[0]
    source = str(candidate["source"])
    scope = str(candidate["path"])
    memory_source_settings.put_settings(
        session, [{"source": source, "enabled": True, "scope": scope}]
    )
    return source, scope


def _external_available(scope: str) -> bool:
    try:
        external_memory.validate_markdown_root(scope)
    except EnishiError:
        return False
    return True


def resolve_backend(session: Session, *, user_id: str) -> MemoryBackendState:
    """正本を一度選んだら、一時切断では内蔵メモリへ戻さない。"""
    state = session.get(MemoryBackendState, user_id)
    if state is None:
        selected = _connected_external_setting(session)
        detected_automatically = False
        if selected is None:
            selected = _auto_detect_external(session)
            detected_automatically = selected is not None
        if selected is None:
            state = MemoryBackendState(
                user_id=user_id,
                primary_source=INTERNAL_SOURCE,
                status=MemoryBackendStatus.INTERNAL_PRIMARY.value,
            )
        else:
            source, scope = selected
            migrating = _active_count(
                session,
                user_id,
                sources={"enishi_mcp", PENDING_SOURCE},
                canonical_only=True,
            )
            state = MemoryBackendState(
                user_id=user_id,
                primary_source=source,
                primary_scope=scope,
                status=(
                    MemoryBackendStatus.MIGRATING.value
                    if migrating
                    else MemoryBackendStatus.EXTERNAL_PRIMARY.value
                ),
                detected_automatically=detected_automatically,
            )
        session.add(state)
        session.commit()
        session.refresh(state)
        return state

    if state.primary_source in EXTERNAL_SOURCES:
        if not _external_available(state.primary_scope):
            state.status = MemoryBackendStatus.EXTERNAL_UNAVAILABLE.value
        else:
            pending = _active_count(
                session,
                user_id,
                sources={"enishi_mcp", PENDING_SOURCE},
                canonical_only=True,
            )
            state.status = (
                MemoryBackendStatus.MIGRATING.value
                if pending
                else MemoryBackendStatus.EXTERNAL_PRIMARY.value
            )
    else:
        selected = _connected_external_setting(session)
        detected_automatically = False
        if selected is None:
            selected = _auto_detect_external(session)
            detected_automatically = selected is not None
        if selected is not None:
            state.primary_source, state.primary_scope = selected
            state.detected_automatically = detected_automatically
            state.status = (
                MemoryBackendStatus.MIGRATING.value
                if _active_count(
                    session,
                    user_id,
                    sources={"enishi_mcp", PENDING_SOURCE},
                    canonical_only=True,
                )
                else MemoryBackendStatus.EXTERNAL_PRIMARY.value
            )
    state.last_checked_at = utc_now()
    session.commit()
    session.refresh(state)
    return state


def _create_internal(
    session: Session,
    *,
    user_id: str,
    title: str,
    text: str,
    memory_type: str,
    sensitivity: str,
    tags: list[str],
    pending_external: bool = False,
) -> MemoryItem:
    source = PENDING_SOURCE if pending_external else "enishi_mcp"
    routed_tags = list(
        dict.fromkeys(tags + (["pending-external-sync"] if pending_external else []))
    )
    return memories.create_memory(
        session,
        user_id=user_id,
        source_type=source,
        source_reference=None,
        memory_type=memory_type,
        title=title[:200],
        content={"text": text, "target_source": "external" if pending_external else "internal"},
        searchable_text=f"{title}\n{text}"[:2000],
        confidence=1.0,
        sensitivity=sensitivity,
        relevance_tags=routed_tags,
    )


def remember(
    session: Session,
    *,
    user_id: str,
    title: str,
    text: str,
    memory_type: str,
    sensitivity: str,
    tags: list[str],
) -> MemoryItem:
    state = resolve_backend(session, user_id=user_id)
    if memory_type not in EXTERNAL_CANONICAL_TYPES:
        return _create_internal(
            session,
            user_id=user_id,
            title=title,
            text=text,
            memory_type=memory_type,
            sensitivity=sensitivity,
            tags=tags,
        )
    if state.status == MemoryBackendStatus.INTERNAL_PRIMARY.value:
        return _create_internal(
            session,
            user_id=user_id,
            title=title,
            text=text,
            memory_type=memory_type,
            sensitivity=sensitivity,
            tags=tags,
        )
    if state.status == MemoryBackendStatus.EXTERNAL_UNAVAILABLE.value:
        return _create_internal(
            session,
            user_id=user_id,
            title=title,
            text=text,
            memory_type=memory_type,
            sensitivity=sensitivity,
            tags=tags,
            pending_external=True,
        )
    try:
        return external_memory.write_markdown_memory(
            session,
            user_id=user_id,
            source=state.primary_source,
            raw_path=state.primary_scope,
            title=title,
            text=text,
            memory_type=memory_type,
            sensitivity=sensitivity,
            tags=tags,
        )
    except (EnishiError, OSError):
        state.status = MemoryBackendStatus.EXTERNAL_UNAVAILABLE.value
        state.last_checked_at = utc_now()
        session.commit()
        return _create_internal(
            session,
            user_id=user_id,
            title=title,
            text=text,
            memory_type=memory_type,
            sensitivity=sensitivity,
            tags=tags,
            pending_external=True,
        )


def migrate_to_external(session: Session, *, user_id: str) -> dict[str, Any]:
    state = resolve_backend(session, user_id=user_id)
    if state.primary_source not in EXTERNAL_SOURCES:
        return {"migrated": 0, "failed": 0, "pending": 0, "status": state.status}
    if not _external_available(state.primary_scope):
        state.status = MemoryBackendStatus.EXTERNAL_UNAVAILABLE.value
        session.commit()
        pending = _active_count(
            session,
            user_id,
            sources={"enishi_mcp", PENDING_SOURCE},
            canonical_only=True,
        )
        return {"migrated": 0, "failed": pending, "pending": pending, "status": state.status}

    candidates = list(
        session.scalars(
            select(MemoryItem)
            .where(
                MemoryItem.user_id == user_id,
                MemoryItem.source_type.in_({"enishi_mcp", PENDING_SOURCE}),
                MemoryItem.memory_type.in_(EXTERNAL_CANONICAL_TYPES),
                MemoryItem.status == MemoryStatus.ACTIVE.value,
            )
            .order_by(MemoryItem.created_at)
        )
    )
    migrated = failed = 0
    for candidate in candidates:
        try:
            external_memory.write_markdown_memory(
                session,
                user_id=user_id,
                source=state.primary_source,
                raw_path=state.primary_scope,
                title=candidate.title,
                text=str(candidate.content.get("text", "")),
                memory_type=candidate.memory_type,
                sensitivity=candidate.sensitivity,
                tags=[
                    tag
                    for tag in candidate.relevance_tags
                    if tag != "pending-external-sync"
                ],
            )
        except (EnishiError, OSError):
            failed += 1
            continue
        candidate.status = MemoryStatus.DELETED.value
        candidate.updated_at = utc_now()
        session.commit()
        migrated += 1

    pending = _active_count(
        session,
        user_id,
        sources={"enishi_mcp", PENDING_SOURCE},
        canonical_only=True,
    )
    state.status = (
        MemoryBackendStatus.EXTERNAL_PRIMARY.value
        if pending == 0
        else MemoryBackendStatus.MIGRATING.value
    )
    state.last_checked_at = utc_now()
    session.commit()
    return {
        "migrated": migrated,
        "failed": failed,
        "pending": pending,
        "status": state.status,
    }


def summary(session: Session, *, user_id: str) -> dict[str, Any]:
    state = resolve_backend(session, user_id=user_id)
    return {
        "primary_source": state.primary_source,
        "primary_scope": state.primary_scope,
        "status": state.status,
        "detected_automatically": state.detected_automatically,
        "pending_count": _active_count(
            session, user_id, sources={PENDING_SOURCE}, canonical_only=True
        ),
        "internal_count": _active_count(
            session, user_id, sources={"enishi_mcp"}, canonical_only=False
        ),
        "last_checked_at": state.last_checked_at,
        "last_synced_at": state.last_synced_at,
    }


def refresh_external_index(
    session: Session, *, user_id: str, force: bool = False
) -> dict[str, int | str] | None:
    """検索前に外部正本の再生成可能な索引を最大1分に1回更新する。"""
    state = resolve_backend(session, user_id=user_id)
    if state.primary_source not in EXTERNAL_SOURCES:
        return None
    if state.status == MemoryBackendStatus.EXTERNAL_UNAVAILABLE.value:
        return None
    last_synced_at = state.last_synced_at
    if last_synced_at is not None and last_synced_at.tzinfo is None:
        last_synced_at = last_synced_at.replace(tzinfo=UTC)
    if (
        not force
        and last_synced_at is not None
        and utc_now() - last_synced_at < timedelta(minutes=1)
    ):
        return None
    result = external_memory.sync_markdown_folder(
        session,
        user_id=user_id,
        source=state.primary_source,
        raw_path=state.primary_scope,
    )
    state.last_synced_at = utc_now()
    session.commit()
    return result
