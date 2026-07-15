"""クローン実行用コンテキストパッケージ生成（enishi.md §20）。"""

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from enishi_core.errors import EnishiError
from enishi_core.models import CloneAgent, CloneContextPackage, LocalProject, MemoryItem
from enishi_core.services.memories import exportable_memories
from enishi_core.services.memory_sources import collect_project_signals
from enishi_core.services.token_counter import estimate_json_tokens

_PROHIBITED_ACTIONS = {
    "delete_files": "ユーザー承認なしのファイル削除",
    "git_push": "git push",
    "git_commit": "git commit",
    "use_network": "外部ネットワーク通信",
    "deploy": "本番デプロイ",
    "install_dependencies": "依存パッケージ追加",
}

_FIXED_PROHIBITED_ACTIONS = ["ホームディレクトリ全体の走査", "APIキーのファイル保存"]
_APPROVAL_REQUIREMENTS = [
    "依存パッケージ追加",
    "DBの破壊的変更",
    "外部ネットワーク通信",
    "ファイル削除",
]


def _dict_to_items(profile: dict[str, Any]) -> dict[str, Any]:
    return dict(profile)


def _decisions_to_list(decisions: Any) -> list[dict[str, Any]]:
    if not isinstance(decisions, dict):
        return []
    return [{"title": title, "content": content} for title, content in decisions.items()]


def _memory_context(memories: list[MemoryItem]) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
]:
    preferences: dict[str, Any] = {}
    skills: dict[str, Any] = {}
    decisions: list[dict[str, Any]] = []
    for memory in memories:
        if memory.memory_type in ("preference", "negative_preference"):
            preferences[memory.title] = memory.content
        elif memory.memory_type == "skill":
            skills[memory.title] = memory.content
        elif memory.memory_type in ("decision", "policy"):
            decisions.append({"title": memory.title, "content": memory.content})
    decisions.sort(key=lambda item: str(item["title"]))
    return preferences, skills, decisions


def _prohibited_actions(coding_profile: dict[str, Any]) -> list[str]:
    approval_rules = coding_profile.get("approval_rules", {})
    actions: list[str] = []
    if isinstance(approval_rules, dict):
        for key, description in _PROHIBITED_ACTIONS.items():
            if approval_rules.get(key) is False:
                actions.append(description)
    for action in _FIXED_PROHIBITED_ACTIONS:
        if action not in actions:
            actions.append(action)
    return actions


def _project_context(project: LocalProject) -> tuple[dict[str, Any], list[str]]:
    signals = collect_project_signals(Path(project.root_path))
    file_references = signals.get("detected_files", [])
    detected_files = file_references if isinstance(file_references, list) else []
    context = {
        "project_id": project.id,
        "name": project.name,
        "root_path": project.root_path,
        "signals": signals,
    }
    return context, [str(item) for item in detected_files]


def _package_payload(
    *,
    clone: CloneAgent,
    task_goal: str,
    project_id: str | None,
    task_id: str | None,
    relevant_project_context: dict[str, Any],
    file_references: list[str],
    exportable: list[MemoryItem],
) -> dict[str, Any]:
    relevant_preferences, relevant_skills, relevant_decisions = _memory_context(exportable)
    coding_rules = clone.coding_profile.get("coding_rules", [])
    if not isinstance(coding_rules, list):
        coding_rules = []

    return {
        "clone_id": clone.id,
        "clone_version": clone.version,
        "task_id": task_id,
        "project_id": project_id,
        "task_goal": task_goal,
        "relevant_preferences": relevant_preferences,
        "relevant_skills": relevant_skills,
        "relevant_project_context": relevant_project_context,
        "relevant_decisions": relevant_decisions,
        "coding_rules": coding_rules,
        "prohibited_actions": _prohibited_actions(clone.coding_profile),
        "approval_requirements": list(_APPROVAL_REQUIREMENTS),
        "file_references": file_references,
    }


def build_context_package(
    session: Session,
    clone_id: str,
    task_goal: str,
    project_id: str | None = None,
    task_id: str | None = None,
    peer_agent_id: str | None = None,
    commit: bool = True,
) -> CloneContextPackage:
    """外部エージェントへ渡す最小コンテキストを生成する（enishi.md 方針修正 §4）。"""
    clone = session.get(CloneAgent, clone_id)
    if clone is None:
        raise EnishiError(
            code="CLONE_NOT_FOUND",
            message="クローンが見つかりません。",
            status_code=404,
            details={"clone_id": clone_id},
        )

    exportable = exportable_memories(session, clone.user_id)
    if peer_agent_id is not None:
        from enishi_core.services.peers import filter_memories_for_peer, get_disclosure_policy

        policy = get_disclosure_policy(session, peer_agent_id)
        exportable = filter_memories_for_peer(exportable, policy)

    relevant_project_context: dict[str, Any] = {}
    file_references: list[str] = []
    if project_id is not None:
        project = session.get(LocalProject, project_id)
        if project is None:
            raise EnishiError(
                code="PROJECT_NOT_FOUND",
                message="プロジェクトが見つかりません。",
                status_code=404,
                details={"project_id": project_id},
            )
        relevant_project_context, file_references = _project_context(project)

    payload = _package_payload(
        clone=clone,
        task_goal=task_goal,
        project_id=project_id,
        task_id=task_id,
        relevant_project_context=relevant_project_context,
        file_references=file_references,
        exportable=exportable,
    )
    estimated_tokens = estimate_json_tokens(payload)
    if estimated_tokens > 20_000:
        raise EnishiError(
            code="CONTEXT_TOO_LARGE",
            message="コンテキストパッケージが大きすぎます。",
            status_code=413,
            details={"estimated_tokens": estimated_tokens},
        )

    content_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    package = CloneContextPackage(
        **payload,
        estimated_tokens=estimated_tokens,
        content_hash=content_hash,
    )
    session.add(package)
    if commit:
        session.commit()
        session.refresh(package)
    else:
        session.flush()
    return package
