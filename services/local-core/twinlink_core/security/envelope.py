"""署名付きメッセージエンベロープ（twinlink.md §25 信頼モデル v2）。

正規化したエンベロープ全体（署名以外の全フィールド）をEd25519で署名し、
受信側で署名・payloadハッシュ・タイムスタンプ許容範囲を検証する。
DBには触れない純関数として実装する。
"""

import base64
import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from twinlink_core.errors import TwinLinkError

PROTOCOL = "twinlink/0.1"


def canonical_bytes(obj: Any) -> bytes:
    """署名対象の正規化バイト列を生成する。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _payload_hash(payload: dict[str, Any], delta: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes({"payload": payload, "delta": delta})).hexdigest()


def _signable_fields(envelope: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in envelope.items() if k != "signature"}


def build_envelope(
    sender: str,
    receiver: str,
    session_id: str,
    message_type: str,
    intent: str,
    session_version: int,
    sequence: int,
    payload: dict[str, Any],
    delta: dict[str, Any],
    requires_human_approval: bool,
    private_key: Ed25519PrivateKey,
) -> dict[str, Any]:
    """署名済みエンベロープを組み立てる。"""
    envelope: dict[str, Any] = {
        "protocol": PROTOCOL,
        "message_id": uuid.uuid4().hex,
        "session_id": session_id,
        "sender_agent_id": sender,
        "receiver_agent_id": receiver,
        "message_type": message_type,
        "intent": intent,
        "session_version": session_version,
        "sequence": sequence,
        "payload": payload,
        "delta": delta,
        "requires_human_approval": requires_human_approval,
        "nonce": secrets.token_hex(16),
        "created_at": datetime.now(UTC).isoformat(),
        "payload_hash": _payload_hash(payload, delta),
    }
    signature = private_key.sign(canonical_bytes(_signable_fields(envelope)))
    envelope["signature"] = base64.b64encode(signature).decode("ascii")
    return envelope


def verify_envelope(
    envelope: dict[str, Any],
    public_key_b64: str,
    *,
    now: datetime | None = None,
    window_seconds: int = 300,
) -> None:
    """署名・payloadハッシュ・タイムスタンプを検証する。違反は例外を送出する。"""
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        signature = base64.b64decode(str(envelope.get("signature", "")))
        public_key.verify(signature, canonical_bytes(_signable_fields(envelope)))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise TwinLinkError(
            code="MESSAGE_SIGNATURE_INVALID",
            message="メッセージ署名の検証に失敗しました。",
            status_code=400,
            details={"message_id": str(envelope.get("message_id", ""))},
        ) from exc

    expected_hash = _payload_hash(
        dict(envelope.get("payload", {})), dict(envelope.get("delta", {}))
    )
    if envelope.get("payload_hash") != expected_hash:
        raise TwinLinkError(
            code="MESSAGE_SIGNATURE_INVALID",
            message="payloadハッシュが一致しません。",
            status_code=400,
            details={"message_id": str(envelope.get("message_id", ""))},
        )

    current = now or datetime.now(UTC)
    created_at = datetime.fromisoformat(str(envelope.get("created_at", "")))
    if abs((current - created_at).total_seconds()) > window_seconds:
        raise TwinLinkError(
            code="MESSAGE_EXPIRED",
            message="メッセージのタイムスタンプが許容範囲外です。",
            status_code=400,
            details={"message_id": str(envelope.get("message_id", ""))},
        )
