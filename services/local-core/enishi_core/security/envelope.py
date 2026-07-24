"""署名付きメッセージエンベロープ（enishi.md §25 信頼モデル v2）。

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
from functools import lru_cache
from pathlib import Path
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from jsonschema import Draft202012Validator

from enishi_core.errors import EnishiError

PROTOCOL = "aun/0.2"
LEGACY_PROTOCOL = "aun/0.1"
MESSAGE_TYPES = {
    "REQUEST",
    "PROPOSE",
    "COUNTER",
    "ACCEPT",
    "REJECT",
    "REQUEST_APPROVAL",
    "APPROVAL_RESULT",
    "EXECUTE",
    "RECEIPT",
    "ERROR",
}
_BASE_FIELDS = {
    "protocol",
    "message_id",
    "session_id",
    "sender_agent_id",
    "receiver_agent_id",
    "message_type",
    "intent",
    "session_version",
    "sequence",
    "payload",
    "delta",
    "requires_human_approval",
    "nonce",
    "created_at",
    "payload_hash",
    "signature",
}
_NODE_FIELDS = {"sender_node_id", "receiver_node_id"}


def _schema_error(message: str, envelope: dict[str, Any]) -> EnishiError:
    return EnishiError(
        code="MESSAGE_SCHEMA_INVALID",
        message=message,
        status_code=400,
        details={"message_id": str(envelope.get("message_id", ""))},
    )


@lru_cache
def _v02_validator() -> Draft202012Validator:
    packaged = (
        Path(__file__).resolve().parents[1]
        / "protocol"
        / "negotiation-message.schema.json"
    )
    source = (
        Path(__file__).resolve().parents[4]
        / "packages"
        / "protocol"
        / "schemas"
        / "negotiation-message.schema.json"
    )
    schema_path = packaged if packaged.exists() else source
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _validate_created_at(envelope: dict[str, Any]) -> None:
    try:
        created_at = datetime.fromisoformat(str(envelope["created_at"]))
    except (KeyError, ValueError) as exc:
        raise _schema_error("created_at が不正です。", envelope) from exc
    if created_at.tzinfo is None:
        raise _schema_error("created_at にはタイムゾーンが必要です。", envelope)


def validate_envelope(envelope: dict[str, Any]) -> None:
    """0.2は公開JSON Schema、0.1は移行用legacy validatorで検証する。"""
    protocol = envelope.get("protocol")
    if protocol == PROTOCOL:
        errors = list(_v02_validator().iter_errors(envelope))
        if errors:
            raise _schema_error("AUN Protocol 0.2 Schemaに適合しません。", envelope)
        _validate_created_at(envelope)
        return
    if protocol != LEGACY_PROTOCOL:
        raise _schema_error("未対応のプロトコルです。", envelope)

    # 0.1受信互換。新規送信には使用せず、廃止時にこの分岐ごと削除する。
    keys = set(envelope)
    missing = _BASE_FIELDS - keys
    node_fields = keys & _NODE_FIELDS
    allowed = _BASE_FIELDS | (_NODE_FIELDS if node_fields else set())
    if missing or keys - allowed:
        raise _schema_error("メッセージの項目構成が不正です。", envelope)
    if node_fields and node_fields != _NODE_FIELDS:
        raise _schema_error("送受信ノードIDは両方必要です。", envelope)

    for field in (
        "message_id",
        "session_id",
        "sender_agent_id",
        "receiver_agent_id",
        "intent",
        "nonce",
        "created_at",
        "payload_hash",
        "signature",
    ):
        if not isinstance(envelope.get(field), str) or not envelope[field]:
            raise _schema_error(f"{field} が不正です。", envelope)
    for field in node_fields:
        if not isinstance(envelope.get(field), str) or not envelope[field]:
            raise _schema_error(f"{field} が不正です。", envelope)
    if envelope.get("message_type") not in MESSAGE_TYPES:
        raise _schema_error("未対応のメッセージ種別です。", envelope)
    if (
        not isinstance(envelope.get("session_version"), int)
        or isinstance(envelope.get("session_version"), bool)
        or envelope["session_version"] < 1
    ):
        raise _schema_error("session_version が不正です。", envelope)
    if (
        not isinstance(envelope.get("sequence"), int)
        or isinstance(envelope.get("sequence"), bool)
        or envelope["sequence"] < 1
    ):
        raise _schema_error("sequence が不正です。", envelope)
    if not isinstance(envelope.get("payload"), dict) or not isinstance(
        envelope.get("delta"), dict
    ):
        raise _schema_error("payloadまたはdeltaが不正です。", envelope)
    if not isinstance(envelope.get("requires_human_approval"), bool):
        raise _schema_error("requires_human_approval が不正です。", envelope)
    _validate_created_at(envelope)


def canonical_bytes(obj: Any, *, protocol: str = PROTOCOL) -> bytes:
    """署名対象を正規化する。0.2はRFC 8785、0.1は旧Python形式。"""
    if protocol == LEGACY_PROTOCOL:
        return json.dumps(
            obj,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    if protocol != PROTOCOL:
        raise ValueError(f"unsupported protocol: {protocol}")
    return rfc8785.dumps(obj)


def _payload_hash(
    payload: dict[str, Any], delta: dict[str, Any], *, protocol: str
) -> str:
    return hashlib.sha256(
        canonical_bytes({"payload": payload, "delta": delta}, protocol=protocol)
    ).hexdigest()


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
    sender_node_id: str | None = None,
    receiver_node_id: str | None = None,
) -> dict[str, Any]:
    """署名済みエンベロープを組み立てる。"""
    # ノードIDを渡さない呼び出しは0.1互換。実Relay経路は必ず0.2を使う。
    protocol = (
        PROTOCOL
        if sender_node_id is not None or receiver_node_id is not None
        else LEGACY_PROTOCOL
    )
    if protocol == PROTOCOL and (
        sender_node_id is None or receiver_node_id is None
    ):
        raise ValueError("sender_node_id and receiver_node_id must be specified together")
    envelope: dict[str, Any] = {
        "protocol": protocol,
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
        "payload_hash": _payload_hash(payload, delta, protocol=protocol),
    }
    if protocol == PROTOCOL:
        envelope["sender_node_id"] = sender_node_id
        envelope["receiver_node_id"] = receiver_node_id
    signature = private_key.sign(
        canonical_bytes(_signable_fields(envelope), protocol=protocol)
    )
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
    validate_envelope(envelope)
    protocol = str(envelope["protocol"])
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        signature = base64.b64decode(str(envelope.get("signature", "")))
        public_key.verify(
            signature,
            canonical_bytes(_signable_fields(envelope), protocol=protocol),
        )
    except (
        InvalidSignature,
        ValueError,
        TypeError,
        rfc8785.CanonicalizationError,
    ) as exc:
        raise EnishiError(
            code="MESSAGE_SIGNATURE_INVALID",
            message="メッセージ署名の検証に失敗しました。",
            status_code=400,
            details={"message_id": str(envelope.get("message_id", ""))},
        ) from exc

    expected_hash = _payload_hash(
        dict(envelope.get("payload", {})),
        dict(envelope.get("delta", {})),
        protocol=protocol,
    )
    if envelope.get("payload_hash") != expected_hash:
        raise EnishiError(
            code="MESSAGE_SIGNATURE_INVALID",
            message="payloadハッシュが一致しません。",
            status_code=400,
            details={"message_id": str(envelope.get("message_id", ""))},
        )

    current = now or datetime.now(UTC)
    created_at = datetime.fromisoformat(str(envelope.get("created_at", "")))
    if abs((current - created_at).total_seconds()) > window_seconds:
        raise EnishiError(
            code="MESSAGE_EXPIRED",
            message="メッセージのタイムスタンプが許容範囲外です。",
            status_code=400,
            details={"message_id": str(envelope.get("message_id", ""))},
        )
