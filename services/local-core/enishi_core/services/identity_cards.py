"""署名付きENISHI名刺の生成と検証。"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy.orm import Session

from enishi_core.config import get_settings
from enishi_core.errors import EnishiError
from enishi_core.models import User
from enishi_core.security.keys import ensure_node_keypair
from enishi_core.services import agent_requests, peers

_SUPPORTED_INTENTS = ["meeting.schedule", "task.request"]
_PROTOCOL_VERSIONS = ["aun/0.1"]


def _unsigned(card: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in card.items() if key != "signature"}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def create_card(session: Session, user_id: str) -> dict[str, Any]:
    user = session.get(User, user_id)
    if user is None:
        raise EnishiError("USER_NOT_FOUND", "ユーザーが見つかりません。", 404)
    personal = agent_requests.ensure_personal_agent(session, user_id)
    node = agent_requests.ensure_device_node(session, personal)
    session.commit()
    _identity, private_key = ensure_node_keypair(get_settings().data_dir)
    card: dict[str, Any] = {
        "version": "enishi-card/2",
        "agent_id": node.node_id,
        "personal_agent_id": personal.id,
        "public_key": node.public_key,
        "fingerprint": node.fingerprint,
        "profile": {"display_name": user.display_name},
        "capabilities": {
            "timezone": user.timezone,
            "supported_intents": _SUPPORTED_INTENTS,
            "protocol_versions": _PROTOCOL_VERSIONS,
        },
        "relay_endpoint": get_settings().relay_url,
        "issued_at": datetime.now(UTC).isoformat(),
    }
    card["signature"] = base64.b64encode(private_key.sign(_unsigned(card))).decode("ascii")
    return card


def verify_card(card: dict[str, Any]) -> dict[str, Any]:
    try:
        public_raw = base64.b64decode(str(card["public_key"]), validate=True)
        signature = base64.b64decode(str(card["signature"]), validate=True)
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, _unsigned(card))
    except (KeyError, ValueError, InvalidSignature) as exc:
        raise EnishiError(
            "IDENTITY_CARD_INVALID",
            "名刺の署名を検証できません。",
            422,
        ) from exc
    expected_agent = "agt_" + hashlib.sha256(public_raw).hexdigest()[:16]
    fingerprint_hex = hashlib.sha256(public_raw).hexdigest()[:16]
    expected_fingerprint = ":".join(
        fingerprint_hex[index : index + 2] for index in range(0, 16, 2)
    )
    if card.get("version") not in {"enishi-card/1", "enishi-card/2"}:
        raise EnishiError("IDENTITY_CARD_INVALID", "未対応の名刺バージョンです。", 422)
    if card.get("agent_id") != expected_agent:
        raise EnishiError("IDENTITY_CARD_INVALID", "名刺のAgent IDが不正です。", 422)
    if card.get("fingerprint") != expected_fingerprint:
        raise EnishiError("IDENTITY_CARD_INVALID", "名刺のfingerprintが不正です。", 422)
    profile = card.get("profile")
    if not isinstance(profile, dict) or not str(profile.get("display_name", "")).strip():
        raise EnishiError("IDENTITY_CARD_INVALID", "名刺の公開プロフィールが不正です。", 422)
    if card.get("version") == "enishi-card/2":
        _validate_capabilities(card.get("capabilities"))
    return card


def _validate_capabilities(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EnishiError("IDENTITY_CARD_INVALID", "名刺の能力宣言が不正です。", 422)
    timezone = value.get("timezone")
    intents = value.get("supported_intents")
    protocols = value.get("protocol_versions")
    try:
        ZoneInfo(str(timezone))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise EnishiError("IDENTITY_CARD_INVALID", "名刺のtimezoneが不正です。", 422) from exc
    if not isinstance(intents, list) or not all(isinstance(item, str) for item in intents):
        raise EnishiError("IDENTITY_CARD_INVALID", "名刺の対応intentが不正です。", 422)
    if not isinstance(protocols, list) or not all(
        isinstance(item, str) for item in protocols
    ):
        raise EnishiError("IDENTITY_CARD_INVALID", "名刺のprotocol versionが不正です。", 422)
    return {
        "timezone": str(timezone),
        "supported_intents": list(dict.fromkeys(intents)),
        "protocol_versions": list(dict.fromkeys(protocols)),
    }


def register_from_card(session: Session, card: dict[str, Any]) -> object:
    verified = verify_card(card)
    local_identity, _private_key = ensure_node_keypair(get_settings().data_dir)
    if verified["agent_id"] == local_identity.agent_id:
        raise EnishiError(
            "SELF_PEER_NOT_ALLOWED",
            "自分自身の名刺は接続相手として登録できません。",
            409,
        )
    return peers.register_peer(
        session,
        agent_id=str(verified["agent_id"]),
        personal_agent_id=str(verified.get("personal_agent_id") or "") or None,
        display_name=str(verified["profile"]["display_name"]),
        public_key=str(verified["public_key"]),
        capabilities=(
            _validate_capabilities(verified.get("capabilities"))
            if verified.get("version") == "enishi-card/2"
            else {}
        ),
    )
