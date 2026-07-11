"""ピアエージェント管理（twinlink.md §25 信頼モデル v2）。

初回ペアリングはpending登録＋ユーザー承認（trust）で行う。
監査ログへは公開鍵本文を入れず、fingerprintのみ記録する。
"""

import base64
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from twinlink_core.errors import TwinLinkError
from twinlink_core.models import MemoryItem, PeerAgent, PeerDisclosurePolicy, PeerStatus
from twinlink_core.services.audit import log_event

_SENSITIVITY_RANK = {
    "public": 0,
    "internal": 1,
    "private": 2,
    "restricted": 3,
    "secret": 4,
}


def _fingerprint(public_key_b64: str) -> str:
    try:
        raw = base64.b64decode(public_key_b64)
    except ValueError:
        raw = public_key_b64.encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def list_peers(session: Session) -> list[PeerAgent]:
    return list(session.scalars(select(PeerAgent).order_by(PeerAgent.created_at.desc())))


def register_peer(
    session: Session, *, agent_id: str, display_name: str, public_key: str
) -> PeerAgent:
    if session.get(PeerAgent, agent_id) is not None:
        raise TwinLinkError(
            code="INVALID_STATE_TRANSITION",
            message="同じagent_idのピアが既に登録されています。",
            status_code=409,
            details={"agent_id": agent_id},
        )
    peer = PeerAgent(
        agent_id=agent_id,
        display_name=display_name,
        public_key=public_key,
        fingerprint=_fingerprint(public_key),
    )
    session.add(peer)
    session.commit()
    session.refresh(peer)

    log_event(
        session,
        event_type="peer_registered",
        payload={"agent_id": peer.agent_id, "fingerprint": peer.fingerprint},
    )
    return peer


def _get_peer(session: Session, agent_id: str) -> PeerAgent:
    peer = session.get(PeerAgent, agent_id)
    if peer is None:
        raise TwinLinkError(
            code="PEER_NOT_FOUND",
            message="ピアが見つかりません。",
            status_code=404,
            details={"agent_id": agent_id},
        )
    return peer


def default_disclosure_policy(agent_id: str) -> PeerDisclosurePolicy:
    """未設定ピア向けの最小公開設定（twinlink.md 方針修正 §4, twinlink.md §17）。"""
    return PeerDisclosurePolicy(
        peer_agent_id=agent_id,
        allowed_memory_types=[],
        max_sensitivity="internal",
        share_schedule=True,
        share_skills=False,
        extra={},
    )


def get_disclosure_policy(session: Session, agent_id: str) -> PeerDisclosurePolicy:
    """相手別の情報公開設定を取得する。未設定時は保存せず既定値を返す。"""
    _get_peer(session, agent_id)
    policy = session.get(PeerDisclosurePolicy, agent_id)
    if policy is None:
        return default_disclosure_policy(agent_id)
    return policy


def put_disclosure_policy(
    session: Session,
    *,
    agent_id: str,
    allowed_memory_types: list[str],
    max_sensitivity: str,
    share_schedule: bool,
    share_skills: bool,
    extra: dict[str, object],
) -> PeerDisclosurePolicy:
    """相手別の情報公開設定を保存する（twinlink.md 方針修正 §4）。"""
    _get_peer(session, agent_id)
    policy = session.get(PeerDisclosurePolicy, agent_id)
    if policy is None:
        policy = PeerDisclosurePolicy(peer_agent_id=agent_id)
        session.add(policy)
    policy.allowed_memory_types = list(allowed_memory_types)
    policy.max_sensitivity = max_sensitivity
    policy.share_schedule = share_schedule
    policy.share_skills = share_skills
    policy.extra = dict(extra)
    session.commit()
    session.refresh(policy)

    log_event(
        session,
        event_type="peer_disclosure_policy_updated",
        payload={
            "agent_id": agent_id,
            "allowed_memory_types": policy.allowed_memory_types,
            "max_sensitivity": policy.max_sensitivity,
            "share_schedule": policy.share_schedule,
            "share_skills": policy.share_skills,
        },
    )
    return policy


def memory_allowed_for_peer(memory: MemoryItem, policy: PeerDisclosurePolicy) -> bool:
    """本文送信・候補計算に使える記憶かを判定する（twinlink.md §17）。"""
    if memory.sensitivity in {"restricted", "secret"}:
        return False
    if memory.memory_type == "schedule" and not policy.share_schedule:
        return False
    if memory.memory_type == "skill" and not policy.share_skills:
        return False
    if memory.memory_type not in set(policy.allowed_memory_types):
        return False
    max_rank = _SENSITIVITY_RANK.get(policy.max_sensitivity, 1)
    sensitivity_rank = _SENSITIVITY_RANK.get(memory.sensitivity, 4)
    return sensitivity_rank <= max_rank


def filter_memories_for_peer(
    memories: list[MemoryItem], policy: PeerDisclosurePolicy
) -> list[MemoryItem]:
    """相手へ公開可能な記憶だけに絞る（twinlink.md 方針修正 §4）。"""
    return [memory for memory in memories if memory_allowed_for_peer(memory, policy)]


def trust_peer(session: Session, agent_id: str) -> PeerAgent:
    """ユーザー承認によりピアをtrustedへ遷移する。"""
    peer = _get_peer(session, agent_id)
    if peer.status == PeerStatus.BLOCKED.value:
        raise TwinLinkError(
            code="INVALID_STATE_TRANSITION",
            message="ブロック済みのピアは信頼できません。",
            status_code=409,
            details={"agent_id": agent_id, "status": peer.status},
        )
    peer.status = PeerStatus.TRUSTED.value
    session.commit()
    session.refresh(peer)

    log_event(
        session,
        event_type="peer_trusted",
        payload={"agent_id": peer.agent_id, "fingerprint": peer.fingerprint},
    )
    return peer


def block_peer(session: Session, agent_id: str) -> PeerAgent:
    peer = _get_peer(session, agent_id)
    peer.status = PeerStatus.BLOCKED.value
    session.commit()
    session.refresh(peer)

    log_event(
        session,
        event_type="peer_blocked",
        payload={"agent_id": peer.agent_id, "fingerprint": peer.fingerprint},
    )
    return peer
