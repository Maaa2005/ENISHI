"""クローン確保ロジック（twinlink.md §14）。

有効なクローンがあれば再利用し、なければ review_required 状態の
ドラフトを生成する。ユーザー確認前に active にはしない。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from twinlink_core.errors import TwinLinkError
from twinlink_core.models import CloneAgent, CloneStatus, User

DEFAULT_CODING_PROFILE: dict[str, Any] = {
    "preferred_languages": ["Python", "TypeScript", "Rust"],
    "coding_rules": [
        "型を付ける",
        "主要ロジックへテストを書く",
        "秘密情報をハードコードしない",
    ],
    "approval_rules": {
        "read_project_files": True,
        "create_files": True,
        "modify_files": True,
        "delete_files": False,
        "run_tests": True,
        "install_dependencies": False,
        "use_network": False,
        "git_commit": False,
        "git_push": False,
        "deploy": False,
    },
}


def get_active_clone(session: Session, user_id: str) -> CloneAgent | None:
    return session.scalars(
        select(CloneAgent).where(
            CloneAgent.user_id == user_id,
            CloneAgent.status == CloneStatus.ACTIVE.value,
        )
    ).first()


def list_clones(session: Session, user_id: str) -> list[CloneAgent]:
    return list(
        session.scalars(
            select(CloneAgent)
            .where(
                CloneAgent.user_id == user_id,
                CloneAgent.status != CloneStatus.DELETED.value,
            )
            .order_by(CloneAgent.created_at.desc())
        )
    )


def ensure_clone(
    session: Session,
    user_id: str,
    purpose: str,
    provider_type: str,
    project_id: str | None = None,
) -> tuple[CloneAgent, bool]:
    """(クローン, 新規生成したか) を返す。"""
    from twinlink_core.services.clone_bootstrap import build_clone_draft

    user = session.get(User, user_id)
    if user is None:
        raise TwinLinkError(
            code="CLONE_NOT_FOUND",
            message="ユーザーが見つかりません。",
            status_code=404,
            details={"user_id": user_id},
        )

    existing = get_active_clone(session, user_id)
    if existing is None:
        # 確認待ちドラフトがあれば再利用し、重複生成を防ぐ
        existing = session.scalars(
            select(CloneAgent)
            .where(
                CloneAgent.user_id == user_id,
                CloneAgent.status == CloneStatus.REVIEW_REQUIRED.value,
            )
            .order_by(CloneAgent.created_at.desc())
        ).first()
    if existing is not None:
        return existing, False

    clone = build_clone_draft(
        session,
        user_id=user_id,
        purpose=purpose,
        provider_type=provider_type,
        project_id=project_id,
    )
    return clone, True


def activate_clone(session: Session, clone_id: str) -> CloneAgent:
    from twinlink_core.models.base import utc_now

    clone = session.get(CloneAgent, clone_id)
    if clone is None:
        raise TwinLinkError(
            code="CLONE_NOT_FOUND",
            message="クローンが見つかりません。",
            status_code=404,
            details={"clone_id": clone_id},
        )
    if clone.status not in (CloneStatus.REVIEW_REQUIRED.value, CloneStatus.PAUSED.value):
        raise TwinLinkError(
            code="INVALID_STATE_TRANSITION",
            message=f"状態 {clone.status} からは有効化できません。",
            status_code=409,
            details={"status": clone.status},
        )
    clone.status = CloneStatus.ACTIVE.value
    clone.activated_at = utc_now()
    # PersonalAgentが既に作成済みなら、委任先クローンを同時に切り替える。
    from twinlink_core.models import PersonalAgent

    personal = session.scalars(
        select(PersonalAgent).where(PersonalAgent.user_id == clone.user_id)
    ).first()
    if personal is not None:
        personal.active_clone_id = clone.id
    session.commit()
    session.refresh(clone)
    return clone
