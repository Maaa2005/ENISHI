"""内部判断理由を、選好を漏らさない粗い公開カテゴリへ変換する。"""

from collections.abc import Iterable

PUBLIC_REASONS = {"no_common_slot", "constraint_violation", "policy_declined"}

_MAPPING = {
    "no_common_slot": "no_common_slot",
    "meeting_outside_preferred_time": "constraint_violation",
    "meeting_time_avoided": "constraint_violation",
    "task_request_policy_threshold_exceeded": "constraint_violation",
    "schedule_negotiation_not_delegated": "policy_declined",
    "task_negotiation_not_delegated": "policy_declined",
    "clone_confidence_below_threshold": "policy_declined",
    "meeting_auto_accept_disabled": "policy_declined",
    "relationship_requires_approval": "policy_declined",
    "human_rejected": "policy_declined",
    "approval_expired": "policy_declined",
}


def to_public_reason(
    reason_codes: Iterable[str], *, default: str = "policy_declined"
) -> str:
    """最初に一致した公開カテゴリだけを返し、内部コードをwireへ出さない。"""
    for code in reason_codes:
        mapped = _MAPPING.get(code)
        if mapped:
            return mapped
    return default if default in PUBLIC_REASONS else "policy_declined"
