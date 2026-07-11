"""ローカルプロジェクトサービス（twinlink.md §24）。

登録パスは正規化し、存在しないパスやホームディレクトリ・ルート直下の登録を拒否する。
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from twinlink_core.errors import TwinLinkError
from twinlink_core.models import LocalProject
from twinlink_core.services.audit import log_event


def _normalize_root_path(root_path: str) -> Path:
    resolved = Path(root_path).expanduser().resolve()

    if not resolved.exists() or not resolved.is_dir():
        raise TwinLinkError(
            code="PROJECT_PATH_NOT_ALLOWED",
            message="指定されたディレクトリが存在しません。",
            status_code=400,
            details={"root_path": root_path},
        )

    home = Path.home().resolve()
    is_filesystem_root = resolved == Path(resolved.anchor)
    if resolved == home or is_filesystem_root:
        raise TwinLinkError(
            code="PROJECT_PATH_NOT_ALLOWED",
            message="ホームディレクトリまたはルート直下は登録できません。",
            status_code=400,
            details={"root_path": root_path},
        )

    return resolved


def _detect_repository_type(root: Path) -> str | None:
    """プロジェクトルート直下の.gitのみを確認する（再帰走査はしない）。"""
    return "git" if (root / ".git").exists() else None


def create_project(session: Session, *, user_id: str, name: str, root_path: str) -> LocalProject:
    resolved = _normalize_root_path(root_path)

    project = LocalProject(
        user_id=user_id,
        name=name,
        root_path=str(resolved),
        repository_type=_detect_repository_type(resolved),
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    log_event(
        session,
        event_type="project_registered",
        user_id=user_id,
        payload={"project_id": project.id, "repository_type": project.repository_type},
    )
    return project


def list_projects(session: Session, user_id: str) -> list[LocalProject]:
    return list(
        session.scalars(
            select(LocalProject)
            .where(LocalProject.user_id == user_id)
            .order_by(LocalProject.created_at.desc())
        )
    )


def get_project(session: Session, project_id: str) -> LocalProject:
    project = session.get(LocalProject, project_id)
    if project is None:
        raise TwinLinkError(
            code="PROJECT_NOT_FOUND",
            message="プロジェクトが見つかりません。",
            status_code=404,
            details={"project_id": project_id},
        )
    return project


def patch_project(
    session: Session,
    project_id: str,
    *,
    permissions: dict[str, bool] | None = None,
    trusted: bool | None = None,
) -> LocalProject:
    project = get_project(session, project_id)
    if permissions is not None:
        project.permissions = permissions
    if trusted is not None:
        project.trusted = trusted
    session.commit()
    session.refresh(project)
    return project
