"""ユーザーごとの本人代理AIポリシー設定。"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from twinlink_core.models import Policy

DELEGATION_DEFAULTS = {
    "schedule_negotiation": True,
    "task_negotiation": True,
    "coding_task": True,
    "external_service_operation": False,
}

APPROVAL_RULE_DEFAULTS = {
    "git_push": True,
    "file_delete": True,
    "external_publish": True,
    "high_value": True,
}


def _get_policy(session: Session, user_id: str, name: str, defaults: dict[str, bool]) -> Policy:
    policy = session.scalars(
        select(Policy).where(Policy.user_id == user_id, Policy.name == name)
    ).first()
    if policy is None:
        policy = Policy(user_id=user_id, name=name, rules=dict(defaults), enabled=True)
        session.add(policy)
        session.commit()
        session.refresh(policy)
    else:
        merged = dict(defaults)
        merged.update({key: bool(value) for key, value in policy.rules.items()})
        policy.rules = merged
        session.commit()
    return policy


def get_delegation(session: Session, user_id: str) -> Policy:
    return _get_policy(session, user_id, "delegation", DELEGATION_DEFAULTS)


def put_delegation(session: Session, user_id: str, rules: dict[str, bool]) -> Policy:
    policy = get_delegation(session, user_id)
    next_rules = dict(DELEGATION_DEFAULTS)
    next_rules.update({key: bool(value) for key, value in rules.items()})
    policy.rules = next_rules
    policy.enabled = True
    session.commit()
    session.refresh(policy)
    return policy


def get_approval_rules(session: Session, user_id: str) -> Policy:
    return _get_policy(session, user_id, "approval_rules", APPROVAL_RULE_DEFAULTS)


def put_approval_rules(session: Session, user_id: str, rules: dict[str, bool]) -> Policy:
    policy = get_approval_rules(session, user_id)
    next_rules = dict(APPROVAL_RULE_DEFAULTS)
    next_rules.update({key: bool(value) for key, value in rules.items()})
    policy.rules = next_rules
    policy.enabled = True
    session.commit()
    session.refresh(policy)
    return policy


def approval_required(session: Session, user_id: str, action: str, default: bool = True) -> bool:
    rules = get_approval_rules(session, user_id).rules
    return bool(rules.get(action, default))


def delegation_enabled(session: Session, user_id: str, action: str, default: bool = True) -> bool:
    rules = get_delegation(session, user_id).rules
    return bool(rules.get(action, default))


def policy_to_dict(policy: Policy) -> dict[str, Any]:
    return {
        "user_id": policy.user_id,
        "name": policy.name,
        "rules": dict(policy.rules),
        "enabled": policy.enabled,
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
    }
