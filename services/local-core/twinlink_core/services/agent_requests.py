"""人間の自然言語依頼を本人エージェントの交渉へ変換するMVP。"""

import re
import unicodedata
from datetime import date, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from twinlink_core.config import get_settings
from twinlink_core.errors import TwinLinkError
from twinlink_core.models import (
    CloneAgent,
    CloneStatus,
    DeviceNode,
    PeerAgent,
    PeerStatus,
    PersonalAgent,
    User,
)
from twinlink_core.security.keys import ensure_node_keypair
from twinlink_core.services.policies import delegation_enabled
from twinlink_core.services.relay_client import RelayTransport

_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_DURATION_RE = re.compile(r"(?<!\d)(\d{1,3})\s*分")
_TIME_RANGE_RE = re.compile(
    r"(?<!\d)(\d{2}:\d{2})\s*(?:〜|～|~|-|から)\s*(\d{2}:\d{2})(?!\d)"
)


def _ambiguous(missing_or_invalid: list[str]) -> TwinLinkError:
    return TwinLinkError(
        code="AGENT_REQUEST_AMBIGUOUS",
        message="依頼を確定できません。日付・所要時間・時間帯を明記してください。",
        status_code=422,
        details={
            "fields": missing_or_invalid,
            "example": "2026-07-20に30分、13:00〜17:00で打ち合わせ",
        },
    )


def interpret_meeting_request(text: str) -> dict[str, Any]:
    """明示されたISO日付・N分・HH:MM範囲だけを決定的に解釈する。"""
    dates = _DATE_RE.findall(text)
    durations = _DURATION_RE.findall(text)
    time_ranges = _TIME_RANGE_RE.findall(text)
    invalid: list[str] = []
    if len(dates) != 1:
        invalid.append("date")
    if len(durations) != 1:
        invalid.append("duration_minutes")
    if len(time_ranges) != 1:
        invalid.append("preferred_time_range")
    if invalid:
        raise _ambiguous(invalid)

    date_value = dates[0]
    duration = int(durations[0])
    start_value, end_value = time_ranges[0]
    try:
        date.fromisoformat(date_value)
        start_time = time.fromisoformat(start_value)
        end_time = time.fromisoformat(end_value)
    except ValueError as exc:
        raise _ambiguous(["date_or_time"]) from exc

    available_minutes = (
        end_time.hour * 60
        + end_time.minute
        - start_time.hour * 60
        - start_time.minute
    )
    if duration < 1 or duration > 480 or available_minutes < duration:
        raise _ambiguous(["duration_or_time_range"])

    return {
        "intent": "meeting.schedule",
        "topic": text.strip()[:500] or "日程調整",
        "duration_minutes": duration,
        "date_range": {"start": date_value, "end": date_value},
        "preferred_time_ranges": [{"start": start_value, "end": end_value}],
    }


def ensure_personal_agent(session: Session, user_id: str) -> PersonalAgent:
    user = session.get(User, user_id)
    if user is None:
        raise TwinLinkError(
            code="USER_NOT_FOUND",
            message="ユーザーが見つかりません。",
            status_code=404,
            details={"user_id": user_id},
        )
    active_clone = session.scalars(
        select(CloneAgent)
        .where(
            CloneAgent.user_id == user_id,
            CloneAgent.status == CloneStatus.ACTIVE.value,
        )
        .order_by(CloneAgent.created_at.desc())
    ).first()
    personal = session.scalars(
        select(PersonalAgent).where(PersonalAgent.user_id == user_id)
    ).first()
    if personal is None:
        personal = PersonalAgent(
            user_id=user_id,
            active_clone_id=active_clone.id if active_clone else None,
        )
        session.add(personal)
        session.flush()
    elif active_clone is not None and personal.active_clone_id != active_clone.id:
        personal.active_clone_id = active_clone.id
        session.flush()
    return personal


def ensure_device_node(session: Session, personal: PersonalAgent) -> DeviceNode:
    identity, _private_key = ensure_node_keypair(get_settings().data_dir)
    node = session.get(DeviceNode, identity.agent_id)
    if node is None:
        node = DeviceNode(
            node_id=identity.agent_id,
            personal_agent_id=personal.id,
            public_key=identity.public_key_b64,
            fingerprint=identity.fingerprint,
        )
        session.add(node)
        session.flush()
    elif node.personal_agent_id != personal.id:
        raise TwinLinkError(
            code="DEVICE_IDENTITY_CONFLICT",
            message="この端末は別の本人エージェントに紐づいています。",
            status_code=409,
            details={"node_id": node.node_id},
        )
    return node


def _peer_candidate(peer: PeerAgent) -> dict[str, Any]:
    return {
        "agent_id": peer.agent_id,
        "personal_agent_id": peer.personal_agent_id,
        "display_name": peer.display_name,
        "aliases": list(peer.aliases or []),
    }


_HONORIFICS = ("さん", "様", "さま", "君", "くん", "ちゃん", "氏")


def _normalize_peer_name(value: str) -> str:
    normalized = "".join(unicodedata.normalize("NFKC", value).casefold().split())
    for suffix in _HONORIFICS:
        normalized_suffix = unicodedata.normalize("NFKC", suffix).casefold()
        if normalized.endswith(normalized_suffix):
            return normalized[: -len(normalized_suffix)]
    return normalized


def resolve_trusted_peer(
    session: Session, peer_agent_id: str | None, text: str = ""
) -> PeerAgent:
    if peer_agent_id is not None:
        peer = session.get(PeerAgent, peer_agent_id)
        if peer is None or peer.status != PeerStatus.TRUSTED.value:
            raise TwinLinkError(
                code="PEER_NOT_TRUSTED",
                message="信頼済みでないピアとは交渉できません。",
                status_code=403,
                details={"agent_id": peer_agent_id},
            )
        return peer

    peers = list(
        session.scalars(
            select(PeerAgent).where(PeerAgent.status == PeerStatus.TRUSTED.value)
        )
    )
    normalized_text = _normalize_peer_name(text)
    matched = [
        peer
        for peer in peers
        if any(
            _normalize_peer_name(name)
            and _normalize_peer_name(name) in normalized_text
            for name in [peer.display_name, *(peer.aliases or [])]
        )
    ]
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        raise TwinLinkError(
            code="AGENT_REQUEST_AMBIGUOUS",
            message="依頼文に複数の接続相手が含まれています。相手を選択してください。",
            status_code=422,
            details={
                "field": "peer_agent_id",
                "candidates": [_peer_candidate(peer) for peer in matched],
            },
        )
    if len(peers) == 1:
        return peers[0]
    raise TwinLinkError(
        code="AGENT_REQUEST_AMBIGUOUS",
        message="依頼先を特定できません。接続相手を選択してください。",
        status_code=422,
        details={
            "field": "peer_agent_id",
            "candidates": [_peer_candidate(peer) for peer in peers],
        },
    )


def submit_agent_request(
    session: Session,
    relay: RelayTransport,
    *,
    user_id: str,
    text: str,
    peer_agent_id: str | None,
) -> object:
    # 曖昧入力はDB/Relayへ副作用を起こす前に拒否する。
    request = interpret_meeting_request(text)
    if not delegation_enabled(
        session, user_id, "schedule_negotiation", default=True
    ):
        raise TwinLinkError(
            code="NEGOTIATION_PERMISSION_DENIED",
            message="日程調整は本人代理AIへ委任されていません。",
            status_code=403,
            details={"operation": "schedule_negotiation"},
        )
    peer = resolve_trusted_peer(session, peer_agent_id, text)
    personal = ensure_personal_agent(session, user_id)
    if personal.active_clone_id is None:
        raise TwinLinkError(
            code="CLONE_REVIEW_REQUIRED",
            message="有効化済みのクローンがありません。",
            status_code=409,
            details={"user_id": user_id},
        )
    ensure_device_node(session, personal)

    from twinlink_core.services.remote_negotiation import start_remote_negotiation

    return start_remote_negotiation(
        session,
        relay,
        user_id=user_id,
        peer_agent_id=peer.agent_id,
        topic=str(request["topic"]),
        duration_minutes=int(request["duration_minutes"]),
        date_range=dict(request["date_range"]),
        preferred_time_ranges=list(request["preferred_time_ranges"]),
    )
