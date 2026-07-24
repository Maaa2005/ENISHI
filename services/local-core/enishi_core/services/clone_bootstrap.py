"""クローン自動生成（enishi.md §14）。

記憶ソース調査→分類→重複除去→矛盾処理→生成を決定的に行う（LLM不使用）。
exportable_memories を通すため secret 記憶はプロフィールへ入らない（§16, §17）。
"""

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from enishi_core.errors import EnishiError
from enishi_core.models import CloneAgent, CloneStatus, MemoryItem, MemorySnapshot, User
from enishi_core.services import memory_sources
from enishi_core.services.audit import log_event
from enishi_core.services.memories import exportable_memories
from enishi_core.services.projects import get_project


def _deduplicate(memories: list[MemoryItem]) -> tuple[list[MemoryItem], int]:
    """(memory_type, title) 単位で重複除去・矛盾処理を行う。

    重複は confidence 最大を採用する。content が異なる矛盾は
    updated_at 最新を優先し、矛盾件数を数える。
    """
    selected: dict[tuple[str, str], MemoryItem] = {}
    conflicts = 0
    for memory in memories:
        key = (memory.memory_type, memory.title)
        current = selected.get(key)
        if current is None:
            selected[key] = memory
            continue
        if memory.content != current.content:
            conflicts += 1
            if memory.updated_at > current.updated_at:
                selected[key] = memory
        elif memory.confidence > current.confidence:
            selected[key] = memory
    return list(selected.values()), conflicts


def _snapshot_id(memories: list[MemoryItem]) -> str:
    joined = ",".join(sorted(m.id for m in memories))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


def _store_memory_snapshot(
    session: Session,
    user_id: str,
    memories: list[MemoryItem],
) -> MemorySnapshot:
    """クローン生成時に使用した記憶IDを保存する（enishi.md §17）。"""
    snapshot = MemorySnapshot(
        id=_snapshot_id(memories),
        user_id=user_id,
        memory_ids=sorted(memory.id for memory in memories),
    )
    existing = session.get(MemorySnapshot, snapshot.id)
    if existing is not None:
        return existing
    session.add(snapshot)
    session.flush()
    return snapshot


def build_clone_draft(
    session: Session,
    user_id: str,
    purpose: str,
    provider_type: str,
    project_id: str | None = None,
) -> CloneAgent:
    """記憶からクローンのドラフトを生成する。生成直後は review_required。"""
    from enishi_core.services.clones import DEFAULT_CODING_PROFILE

    user = session.get(User, user_id)
    if user is None:
        raise EnishiError(
            code="CLONE_NOT_FOUND",
            message="ユーザーが見つかりません。",
            status_code=404,
            details={"user_id": user_id},
        )

    memories, conflicts = _deduplicate(exportable_memories(session, user_id))

    preference_profile: dict[str, Any] = {}
    skill_profile: dict[str, Any] = {}
    project_profile: dict[str, Any] = {}
    communication_profile: dict[str, Any] = {}
    policy_decisions: dict[str, Any] = {}
    environment: dict[str, Any] = {}

    for memory in memories:
        if memory.memory_type in ("preference", "negative_preference"):
            preference_profile[memory.title] = memory.content
        elif memory.memory_type == "skill":
            skill_profile[memory.title] = memory.content
        elif memory.memory_type in ("project", "project_state"):
            project_profile[memory.title] = memory.content
        elif memory.memory_type == "communication":
            communication_profile[memory.title] = memory.content
        elif memory.memory_type == "environment":
            environment[memory.title] = memory.content
        elif memory.memory_type in ("decision", "policy"):
            policy_decisions[memory.title] = memory.content

    coding_profile: dict[str, Any] = {
        **DEFAULT_CODING_PROFILE,
        "preferred_languages": list(DEFAULT_CODING_PROFILE["preferred_languages"]),
    }
    if environment:
        coding_profile["environment"] = environment

    has_project = False
    if project_id is not None:
        project = get_project(session, project_id)
        root = Path(project.root_path)
        signals = memory_sources.collect_project_signals(root)
        git_signals = memory_sources.collect_git_signals(root)
        project_profile["active_project"] = {
            "project_id": project.id,
            "name": project.name,
            "signals": signals,
            "git": git_signals,
        }
        has_project = True

        preferred = coding_profile["preferred_languages"]
        merged = [lang for lang in signals["languages"] if lang not in preferred]
        coding_profile["preferred_languages"] = merged + preferred

    policy_profile: dict[str, Any] = {
        "purpose": purpose,
        "provider_type": provider_type,
        "conflicts": conflicts,
        "task_request": {
            "max_hours_auto_accept": 2.0,
            "max_hours_auto_counter": 4.0,
            "min_deadline_margin_days": 1,
        },
    }
    if policy_decisions:
        policy_profile["decisions"] = policy_decisions

    snapshot = _store_memory_snapshot(session, user_id, memories)

    clone = CloneAgent(
        user_id=user_id,
        name=f"{user.display_name}のクローン",
        status=CloneStatus.REVIEW_REQUIRED.value,
        identity_profile={"display_name": user.display_name, "language": user.language},
        preference_profile=preference_profile,
        skill_profile=skill_profile,
        project_profile=project_profile,
        communication_profile=communication_profile,
        coding_profile=coding_profile,
        policy_profile=policy_profile,
        memory_snapshot_id=snapshot.id,
        confidence_score=min(0.9, 0.3 + 0.05 * len(memories)),
    )
    session.add(clone)
    session.commit()
    session.refresh(clone)

    log_event(
        session,
        event_type="clone_bootstrap_completed",
        user_id=user_id,
        clone_id=clone.id,
        payload={
            "memory_count": len(memories),
            "conflicts": conflicts,
            "has_project": has_project,
        },
    )
    return clone


def rebuild_clone(session: Session, clone_id: str) -> CloneAgent:
    """既存クローンを最新の記憶で再生成する（enishi.md §30 /rebuild）。"""
    old = session.get(CloneAgent, clone_id)
    if old is None:
        raise EnishiError(
            code="CLONE_NOT_FOUND",
            message="クローンが見つかりません。",
            status_code=404,
            details={"clone_id": clone_id},
        )
    if old.status == CloneStatus.DELETED.value:
        raise EnishiError(
            code="INVALID_STATE_TRANSITION",
            message="削除済みクローンは再生成できません。",
            status_code=409,
            details={"status": old.status},
        )

    purpose = str(old.policy_profile.get("purpose", ""))
    provider_type = str(old.policy_profile.get("provider_type", ""))
    new_clone = build_clone_draft(
        session,
        user_id=old.user_id,
        purpose=purpose,
        provider_type=provider_type,
    )
    new_clone.version = old.version + 1
    old.status = CloneStatus.OUTDATED.value
    session.commit()
    session.refresh(new_clone)
    return new_clone
