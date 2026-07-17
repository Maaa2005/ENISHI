"""外部コーディングエージェントタスクサービス（enishi.md §23, §31）。"""

import asyncio
import contextlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from enishi_core.config import get_settings
from enishi_core.database import get_session
from enishi_core.errors import EnishiError
from enishi_core.models import (
    Approval,
    ApprovalStatus,
    CloneAgent,
    CloneContextPackage,
    CloneStatus,
    CodingTask,
    CodingTaskStatus,
    LocalProject,
    User,
)
from enishi_core.models.base import utc_now
from enishi_core.providers import get_adapter
from enishi_core.providers.base import CodingTaskResult
from enishi_core.services.approvals import create_approval
from enishi_core.services.audit import log_event
from enishi_core.services.context_builder import build_context_package
from enishi_core.services.policies import approval_required, delegation_enabled

LEVEL3_OPERATIONS = {
    "git_push",
    "deploy",
    "read_home_directory",
    "send_secrets",
    "rm_rf",
    "git_reset_hard",
    "git_clean",
    "sudo",
}
LEVEL2_OPERATIONS = {
    "install_dependencies",
    "db_migration",
    "delete_files",
    "use_network",
    "git_commit",
    "modify_config",
}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_TERMINAL_STATUSES_WITH_EXPIRED = {"completed", "failed", "cancelled", "expired"}
_PROJECT_PERMISSION_ALIASES = {"delete_files": "delete"}
_APPROVAL_RULE_ACTIONS = {
    "delete_files": "file_delete",
    "use_network": "external_publish",
    "git_push": "git_push",
    "deploy": "external_publish",
}


def _validate_user_and_clone(session: Session, user_id: str, clone_id: str) -> CloneAgent:
    user = session.get(User, user_id)
    if user is None:
        raise EnishiError(
            code="USER_NOT_FOUND",
            message="ユーザーが見つかりません。",
            status_code=404,
            details={"user_id": user_id},
        )
    clone = session.get(CloneAgent, clone_id)
    if clone is None:
        raise EnishiError(
            code="CLONE_NOT_FOUND",
            message="クローンが見つかりません。",
            status_code=404,
            details={"clone_id": clone_id},
        )
    if clone.user_id != user_id or clone.status != CloneStatus.ACTIVE.value:
        raise EnishiError(
            code="CLONE_REVIEW_REQUIRED",
            message="クローンのレビュー完了が必要です。",
            status_code=409,
            details={"clone_id": clone_id, "status": clone.status},
        )
    return clone


def _validate_operations(
    project: LocalProject | None,
    requested_operations: list[str],
) -> None:
    forbidden_level3 = sorted(set(requested_operations) & LEVEL3_OPERATIONS)
    if forbidden_level3:
        raise EnishiError(
            code="TASK_PERMISSION_DENIED",
            message="この操作はMVPでは許可されていません。",
            status_code=403,
            details={"operations": forbidden_level3},
        )

    if project is None:
        return
    denied = []
    for operation in requested_operations:
        permission_key = _PROJECT_PERMISSION_ALIASES.get(operation, operation)
        if project.permissions.get(permission_key) is False:
            denied.append(operation)
    if denied:
        raise EnishiError(
            code="TASK_PERMISSION_DENIED",
            message="プロジェクト権限で禁止された操作です。",
            status_code=403,
            details={"operations": denied, "project_id": project.id},
        )


def _project_root(project: LocalProject | None) -> Path:
    if project is None:
        return Path.cwd()
    return Path(project.root_path)


def _load_task_execution_context(
    session: Session,
    task: CodingTask,
) -> tuple[CloneContextPackage, LocalProject | None]:
    context_package = session.get(CloneContextPackage, task.context_package_id)
    if context_package is None:
        raise EnishiError(
            code="CONTEXT_PACKAGE_NOT_FOUND",
            message="コンテキストパッケージが見つかりません。",
            status_code=404,
            details={"context_package_id": task.context_package_id},
        )
    project = session.get(LocalProject, task.project_id) if task.project_id is not None else None
    return context_package, project


def _mark_task_finished(
    session: Session,
    task: CodingTask,
    *,
    status: str,
    result: CodingTaskResult | None = None,
    failure_code: str | None = None,
    failure_message: str | None = None,
) -> CodingTask:
    task.status = status
    if result is not None:
        task.output_lines = result.output_lines
        task.result = {"detail": result.detail}
    task.failure_code = failure_code
    task.failure_message = failure_message
    task.finished_at = utc_now()
    task.heartbeat_at = task.finished_at
    session.commit()
    session.refresh(task)

    log_event(
        session,
        event_type="coding_agent_task_completed",
        user_id=task.user_id,
        clone_id=task.clone_id,
        payload={
            "provider": task.provider,
            "task_id": task.id,
            "status": task.status,
            "failure_code": failure_code,
        },
    )
    return task


def create_task(
    session: Session,
    user_id: str,
    clone_id: str,
    provider: str,
    description: str,
    project_id: str | None = None,
    requested_operations: list[str] | None = None,
    approval_expires_at: datetime | None = None,
) -> CodingTask:
    operations = requested_operations or []
    _validate_user_and_clone(session, user_id, clone_id)
    if not delegation_enabled(session, user_id, "coding_task", default=True):
        raise EnishiError(
            code="TASK_PERMISSION_DENIED",
            message="コーディングタスクは委任されていません。",
            status_code=403,
            details={"operation": "coding_task"},
        )
    project = session.get(LocalProject, project_id) if project_id is not None else None
    if project_id is not None and project is None:
        raise EnishiError(
            code="PROJECT_NOT_FOUND",
            message="プロジェクトが見つかりません。",
            status_code=404,
            details={"project_id": project_id},
        )
    _validate_operations(project, operations)
    get_adapter(provider)

    level2_operations = sorted(
        operation
        for operation in set(operations) & LEVEL2_OPERATIONS
        if approval_required(
            session, user_id, _APPROVAL_RULE_ACTIONS.get(operation, operation), default=True
        )
    )
    requires_approval = bool(level2_operations)
    initial_status = (
        CodingTaskStatus.WAITING_APPROVAL.value
        if requires_approval
        else CodingTaskStatus.QUEUED.value
    )
    queued_at = None if requires_approval else utc_now()
    task = CodingTask(
        user_id=user_id,
        clone_id=clone_id,
        project_id=project_id,
        provider=provider,
        description=description,
        status=initial_status,
        queued_at=queued_at,
        output_lines=[],
        result={},
        timeout_seconds=get_settings().timeout_for_provider(provider),
    )
    session.add(task)
    session.flush()

    context_package = build_context_package(
        session,
        clone_id=clone_id,
        task_goal=description,
        project_id=project_id,
        task_id=task.id,
        commit=False,
    )
    task.context_package_id = context_package.id

    if level2_operations:
        approval = create_approval(
            session,
            user_id=user_id,
            action_type=",".join(level2_operations),
            description="コーディングエージェントタスクの承認が必要です。",
            level=2,
            payload={"task_id": task.id},
            expires_at=approval_expires_at,
            commit=False,
        )
        task.approval_id = approval.id
    session.commit()
    session.refresh(task)

    log_event(
        session,
        event_type="coding_agent_task_started",
        user_id=user_id,
        clone_id=clone_id,
        payload={
            "provider": provider,
            "task_id": task.id,
            "context_tokens": context_package.estimated_tokens,
            "permissions": operations,
        },
    )

    return task


def on_approval_resolved(session: Session, approval: Approval) -> None:
    task_id = approval.payload.get("task_id")
    if not isinstance(task_id, str):
        return
    task = session.get(CodingTask, task_id)
    if task is None or task.status != CodingTaskStatus.WAITING_APPROVAL.value:
        return
    if approval.status == ApprovalStatus.APPROVED.value:
        task.status = CodingTaskStatus.QUEUED.value
        task.queued_at = utc_now()
        session.commit()
        return
    if approval.status == ApprovalStatus.REJECTED.value:
        task.status = CodingTaskStatus.CANCELLED.value
        task.finished_at = utc_now()
        session.commit()
        return
    if approval.status == ApprovalStatus.EXPIRED.value:
        expire_task_for_approval(session, approval)


def expire_task_for_approval(session: Session, approval: Approval) -> None:
    """承認失効によりwaiting_approvalタスクをexpiredへ終端化する。"""
    task_id = approval.payload.get("task_id")
    if not isinstance(task_id, str):
        return
    task = session.get(CodingTask, task_id)
    if task is None or task.status != CodingTaskStatus.WAITING_APPROVAL.value:
        return
    task.status = CodingTaskStatus.EXPIRED.value
    task.finished_at = utc_now()
    task.failure_code = "APPROVAL_EXPIRED"
    task.failure_message = "承認期限が切れました。"
    session.commit()


def cancel_task(session: Session, task_id: str) -> CodingTask:
    task = get_task(session, task_id)
    if (
        task.status in _TERMINAL_STATUSES_WITH_EXPIRED
        or task.status == CodingTaskStatus.CANCELLING.value
    ):
        raise EnishiError(
            code="INVALID_STATE_TRANSITION",
            message=f"状態 {task.status} からは変更できません。",
            status_code=409,
            details={"status": task.status},
        )
    if task.status == CodingTaskStatus.RUNNING.value:
        task.status = CodingTaskStatus.CANCELLING.value
    else:
        task.status = CodingTaskStatus.CANCELLED.value
        task.finished_at = utc_now()
    session.commit()
    session.refresh(task)
    return task


def get_task(session: Session, task_id: str) -> CodingTask:
    task = session.get(CodingTask, task_id)
    if task is None:
        raise EnishiError(
            code="TASK_NOT_FOUND",
            message="タスクが見つかりません。",
            status_code=404,
            details={"task_id": task_id},
        )
    if task.approval_id is not None:
        from enishi_core.services.approvals import get_approval

        approval = get_approval(session, task.approval_id)
        on_approval_resolved(session, approval)
        session.refresh(task)
    return task


def list_tasks(
    session: Session,
    *,
    user_id: str | None = None,
    limit: int = 50,
) -> list[CodingTask]:
    """新しい順にタスク履歴を返す。必要なら本人で絞り込む。"""
    query = select(CodingTask)
    if user_id is not None:
        query = query.where(CodingTask.user_id == user_id)
    return list(
        session.scalars(
            query.order_by(CodingTask.created_at.desc()).limit(limit)
        )
    )


def recover_interrupted_tasks(session: Session) -> int:
    """起動時に残ったrunning/cancellingタスクをfailedへ倒す（enishi.md §30）。"""
    now = utc_now()
    result = session.execute(
        update(CodingTask)
        .where(
            CodingTask.status.in_(
                [CodingTaskStatus.RUNNING.value, CodingTaskStatus.CANCELLING.value]
            )
        )
        .values(
            status=CodingTaskStatus.FAILED.value,
            failure_code="WORKER_INTERRUPTED",
            failure_message="ワーカー停止中にタスクが中断されました。",
            finished_at=now,
            heartbeat_at=now,
        )
    )
    session.commit()
    return int(cast(Any, result).rowcount or 0)


def claim_next_task(session: Session, worker_id: str) -> CodingTask | None:
    """queuedタスクを条件付きUPDATEで1件だけclaimする（enishi.md §30）。"""
    task_id = session.scalar(
        select(CodingTask.id)
        .where(CodingTask.status == CodingTaskStatus.QUEUED.value)
        .order_by(CodingTask.queued_at, CodingTask.created_at)
        .limit(1)
    )
    if task_id is None:
        return None

    now = utc_now()
    result = session.execute(
        update(CodingTask)
        .where(
            CodingTask.id == task_id,
            CodingTask.status == CodingTaskStatus.QUEUED.value,
        )
        .values(
            status=CodingTaskStatus.RUNNING.value,
            started_at=now,
            heartbeat_at=now,
            worker_id=worker_id,
        )
    )
    session.commit()
    if cast(Any, result).rowcount != 1:
        return None
    task = session.get(CodingTask, task_id)
    return task


def _session() -> Session:
    return next(get_session())


def _refresh_heartbeat(task_id: str) -> None:
    session = _session()
    try:
        task = session.get(CodingTask, task_id)
        if task is not None and task.status == CodingTaskStatus.RUNNING.value:
            task.heartbeat_at = utc_now()
            session.commit()
    finally:
        session.close()


def _task_status(task_id: str) -> str | None:
    session = _session()
    try:
        return session.scalar(select(CodingTask.status).where(CodingTask.id == task_id))
    finally:
        session.close()


async def _run_claimed_task(task_id: str) -> None:
    session = _session()
    try:
        task = session.get(CodingTask, task_id)
        if task is None:
            return
        context_package, project = _load_task_execution_context(session, task)
        adapter = get_adapter(task.provider)
        provider_task = asyncio.create_task(
            adapter.run_task(task.description, context_package, _project_root(project))
        )
        try:
            result = await _wait_for_provider_task(task, provider_task)
        except TimeoutError:
            provider_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await provider_task
            task = session.get(CodingTask, task_id)
            if task is not None:
                _mark_task_finished(
                    session,
                    task,
                    status=CodingTaskStatus.FAILED.value,
                    failure_code="TASK_TIMEOUT",
                    failure_message="タスクがタイムアウトしました。",
                )
            return
        except asyncio.CancelledError:
            provider_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await provider_task
            task = session.get(CodingTask, task_id)
            if task is not None and task.status == CodingTaskStatus.CANCELLING.value:
                _mark_task_finished(session, task, status=CodingTaskStatus.CANCELLED.value)
                return
            raise

        task = session.get(CodingTask, task_id)
        if task is None:
            return
        if task.status == CodingTaskStatus.CANCELLING.value:
            _mark_task_finished(session, task, status=CodingTaskStatus.CANCELLED.value)
            return
        status = (
            CodingTaskStatus.COMPLETED.value
            if result.status == CodingTaskStatus.COMPLETED.value
            else CodingTaskStatus.FAILED.value
        )
        failure_code = None if status == CodingTaskStatus.COMPLETED.value else "PROVIDER_FAILED"
        failure_message = None if status == CodingTaskStatus.COMPLETED.value else result.detail
        _mark_task_finished(
            session,
            task,
            status=status,
            result=result,
            failure_code=failure_code,
            failure_message=failure_message,
        )
    except Exception as exc:
        task = session.get(CodingTask, task_id)
        if task is not None:
            _mark_task_finished(
                session,
                task,
                status=CodingTaskStatus.FAILED.value,
                failure_code="TASK_EXECUTION_ERROR",
                failure_message=str(exc),
            )
    finally:
        session.close()


async def _wait_for_provider_task(
    task: CodingTask,
    provider_task: asyncio.Task[CodingTaskResult],
) -> CodingTaskResult:
    deadline = asyncio.get_running_loop().time() + task.timeout_seconds
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError
        done, _pending = await asyncio.wait({provider_task}, timeout=min(0.25, remaining))
        if done:
            return provider_task.result()
        status = _task_status(task.id)
        if status == CodingTaskStatus.CANCELLING.value:
            provider_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await provider_task
            return CodingTaskResult(status="cancelled", output_lines=[], detail="cancelled")
        _refresh_heartbeat(task.id)


async def worker_loop(stop_event: asyncio.Event) -> None:
    """単一ワーカー・並行数1でCodingTaskキューを処理する（enishi.md §30）。"""
    settings = get_settings()
    worker_id = f"{settings.task_worker_id}-{uuid.uuid4().hex[:8]}"
    poll_interval = settings.task_worker_poll_interval_seconds

    while not stop_event.is_set():
        session = _session()
        try:
            task = claim_next_task(session, worker_id)
        finally:
            session.close()
        if task is None:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            continue
        await _run_claimed_task(task.id)
