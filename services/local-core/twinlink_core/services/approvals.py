"""承認サービス（twinlink.md §31, §32）。"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from twinlink_core.config import get_settings
from twinlink_core.errors import TwinLinkError
from twinlink_core.models import Approval, ApprovalStatus
from twinlink_core.models.base import utc_now
from twinlink_core.services.audit import log_event


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def create_approval(
    session: Session,
    *,
    user_id: str,
    action_type: str,
    description: str,
    level: int,
    payload: dict[str, Any] | None = None,
    expires_at: datetime | None = None,
    commit: bool = True,
) -> Approval:
    now = utc_now()
    approval = Approval(
        user_id=user_id,
        action_type=action_type,
        description=description,
        level=level,
        payload=payload or {},
        created_at=now,
        expires_at=expires_at or now + timedelta(seconds=get_settings().approval_ttl_seconds),
    )
    session.add(approval)
    if commit:
        session.commit()
        session.refresh(approval)
    else:
        session.flush()
    return approval


def expire_if_needed(session: Session, approval: Approval) -> Approval:
    """期限切れpending承認をexpiredへ遅延遷移する（twinlink.md §31）。"""
    if approval.status != ApprovalStatus.PENDING.value:
        return approval
    now = utc_now()
    if _as_utc(approval.expires_at) > now:
        return approval

    approval.status = ApprovalStatus.EXPIRED.value
    approval.resolved_at = now
    session.commit()
    session.refresh(approval)

    from twinlink_core.services.tasks import expire_task_for_approval

    expire_task_for_approval(session, approval)
    from twinlink_core.services.negotiation import on_approval_resolved

    on_approval_resolved(session, approval)
    log_event(
        session,
        event_type="approval_expired",
        user_id=approval.user_id,
        payload={"approval_id": approval.id, "action_type": approval.action_type},
    )
    return approval


def get_approval(session: Session, approval_id: str) -> Approval:
    """承認を取得し、期限切れならexpiredへ遷移する。"""
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise TwinLinkError(
            code="APPROVAL_REQUIRED",
            message="承認対象が見つかりません。",
            status_code=404,
            details={"approval_id": approval_id},
        )
    return expire_if_needed(session, approval)


def list_approvals(session: Session, user_id: str | None = None) -> list[Approval]:
    """pending状態を先頭に、作成日時の新しい順で返す。"""
    pending_first = case((Approval.status == ApprovalStatus.PENDING.value, 0), else_=1)
    query = select(Approval).order_by(pending_first, Approval.created_at.desc())
    if user_id is not None:
        query = query.where(Approval.user_id == user_id)
    approvals = list(session.scalars(query))
    return [expire_if_needed(session, approval) for approval in approvals]


def _get_pending_approval(session: Session, approval_id: str) -> Approval:
    approval = get_approval(session, approval_id)
    if approval.status != ApprovalStatus.PENDING.value:
        code = (
            "APPROVAL_EXPIRED"
            if approval.status == ApprovalStatus.EXPIRED.value
            else "INVALID_STATE_TRANSITION"
        )
        raise TwinLinkError(
            code=code,
            message=f"状態 {approval.status} からは変更できません。",
            status_code=409,
            details={"status": approval.status},
        )
    return approval


def approve(session: Session, approval_id: str) -> Approval:
    approval = _get_pending_approval(session, approval_id)
    approval.status = ApprovalStatus.APPROVED.value
    approval.resolved_at = utc_now()
    session.commit()
    session.refresh(approval)

    log_event(
        session,
        event_type="approval_approved",
        user_id=approval.user_id,
        payload={"approval_id": approval.id, "action_type": approval.action_type},
    )
    return approval


def reject(session: Session, approval_id: str) -> Approval:
    approval = _get_pending_approval(session, approval_id)
    approval.status = ApprovalStatus.REJECTED.value
    approval.resolved_at = utc_now()
    session.commit()
    session.refresh(approval)

    log_event(
        session,
        event_type="approval_rejected",
        user_id=approval.user_id,
        payload={"approval_id": approval.id, "action_type": approval.action_type},
    )
    return approval
