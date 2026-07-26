"""人間の自然言語依頼を本人エージェントの交渉へ変換するMVP。"""

import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from enishi_core.config import get_settings
from enishi_core.domains import get_domain
from enishi_core.domains.meeting_schedule import (
    INTENT_MEETING_SCHEDULE,
    MeetingScheduleRequest,
)
from enishi_core.errors import EnishiError
from enishi_core.models import (
    CloneAgent,
    CloneStatus,
    DeviceNode,
    PeerAgent,
    PeerStatus,
    PersonalAgent,
    User,
)
from enishi_core.security.keys import ensure_node_keypair
from enishi_core.services.intent_interpreter import DeterministicInterpreter, get_interpreter
from enishi_core.services.policies import delegation_enabled
from enishi_core.services.relay_client import RelayTransport


def interpret_meeting_request(text: str) -> dict[str, Any]:
    """後方互換ラッパ。実体は `intent_interpreter.DeterministicInterpreter` へ移設済み
    （既存テストが直接importしている可能性があるため残す）。
    """
    interpreted = DeterministicInterpreter().interpret(text)
    return {"intent": interpreted.intent, **interpreted.payload}


@dataclass
class _InterpretedNegotiationRequest:
    """`get_interpreter().interpret()` の結果を `DecisionDomain.validate_request()` へ渡すための
    `NegotiationRequestLike` 実装（`domains/base.py` 参照）。

    `NegotiationRequestLike` は属性への代入可能性まで構造的に要求するため（mypyの
    Protocol互換チェック）、frozenにはしない。
    """

    intent: str
    initiator_user_id: str
    responder_user_id: str
    payload: dict[str, Any]


def ensure_personal_agent(session: Session, user_id: str) -> PersonalAgent:
    user = session.get(User, user_id)
    if user is None:
        raise EnishiError(
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
        raise EnishiError(
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
            raise EnishiError(
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
        raise EnishiError(
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
    raise EnishiError(
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
    # 曖昧入力・未知intentはDB/Relayへ副作用を起こす前に拒否する（LLMの出力は必ずここを通す）。
    interpreted = get_interpreter(get_settings(), session=session).interpret(text)
    domain = get_domain(interpreted.intent)
    validated = domain.validate_request(
        _InterpretedNegotiationRequest(
            intent=interpreted.intent,
            initiator_user_id=user_id,
            responder_user_id="",
            payload=interpreted.payload,
        )
    )
    if interpreted.intent != INTENT_MEETING_SCHEDULE:
        # Relay経由の遠隔交渉（start_remote_negotiation）は現状meeting.scheduleのみ対応。
        # 他ドメインの遠隔交渉ドライバはPhase Cの範囲外（禁止事項: DBスキーマ変更なし）。
        raise EnishiError(
            code="INTENT_NOT_SUPPORTED_FOR_REMOTE_REQUEST",
            message="このドメインはまだ自然言語依頼からの遠隔交渉に対応していません。",
            status_code=422,
            details={"intent": interpreted.intent},
        )
    assert isinstance(validated, MeetingScheduleRequest)

    if not delegation_enabled(
        session, user_id, "schedule_negotiation", default=True
    ):
        raise EnishiError(
            code="NEGOTIATION_PERMISSION_DENIED",
            message="日程調整は本人代理AIへ委任されていません。",
            status_code=403,
            details={"operation": "schedule_negotiation"},
        )
    peer = resolve_trusted_peer(session, peer_agent_id, text)
    personal = ensure_personal_agent(session, user_id)
    if personal.active_clone_id is None:
        raise EnishiError(
            code="CLONE_REVIEW_REQUIRED",
            message="有効化済みのクローンがありません。",
            status_code=409,
            details={"user_id": user_id},
        )
    ensure_device_node(session, personal)

    from enishi_core.services.remote_negotiation import start_remote_negotiation

    return start_remote_negotiation(
        session,
        relay,
        user_id=user_id,
        peer_agent_id=peer.agent_id,
        topic=validated.topic,
        duration_minutes=validated.duration_minutes,
        date_range=dict(validated.date_range),
        preferred_time_ranges=list(validated.preferred_time_ranges),
    )
