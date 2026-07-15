"""ノード鍵ペア管理（twinlink.md §25 信頼モデル v2）。

Agent IDはEd25519公開鍵から導出する。

Tauri起動時はmacOS Keychainへ保存し、CLIデモ時だけ0600ファイルへ
フォールバックする。既存のファイル鍵は初回Tauri起動時にKeychainへ移行する。
"""

import base64
import binascii
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel

_KEY_FILENAME = "node_ed25519.key"
_KEYRING_ACCOUNT = "node-ed25519-private-key"


class NodeIdentity(BaseModel):
    agent_id: str
    public_key_b64: str
    fingerprint: str


def _fingerprint(public_raw: bytes) -> str:
    digest = hashlib.sha256(public_raw).hexdigest()[:16]
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def _identity_from_private(private_key: Ed25519PrivateKey) -> NodeIdentity:
    public_raw = private_key.public_key().public_bytes_raw()
    return NodeIdentity(
        agent_id="agt_" + hashlib.sha256(public_raw).hexdigest()[:16],
        public_key_b64=base64.b64encode(public_raw).decode("ascii"),
        fingerprint=_fingerprint(public_raw),
    )


def _keyring_get(service: str) -> str | None:
    import keyring

    return keyring.get_password(service, _KEYRING_ACCOUNT)


def _keyring_set(service: str, value: str) -> None:
    import keyring

    keyring.set_password(service, _KEYRING_ACCOUNT, value)


def _private_key_from_encoded(value: str) -> Ed25519PrivateKey:
    try:
        raw = base64.b64decode(value, validate=True)
        return Ed25519PrivateKey.from_private_bytes(raw)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("Keychainのノード署名鍵が不正です。") from exc


def _ensure_keyring_keypair(
    service: str, key_path: Path
) -> tuple[NodeIdentity, Ed25519PrivateKey]:
    encoded = _keyring_get(service)
    if encoded:
        private_key = _private_key_from_encoded(encoded)
    elif key_path.exists():
        # 旧Tauri版の0600ファイル鍵を移行し、Agent IDを維持する。
        private_key = Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())
        _keyring_set(service, base64.b64encode(private_key.private_bytes_raw()).decode("ascii"))
    else:
        private_key = Ed25519PrivateKey.generate()
        _keyring_set(service, base64.b64encode(private_key.private_bytes_raw()).decode("ascii"))

    # Keychainを正とした後は平文ファイルを残さない。
    if key_path.exists():
        key_path.unlink()
    return _identity_from_private(private_key), private_key


def ensure_node_keypair(data_dir: Path) -> tuple[NodeIdentity, Ed25519PrivateKey]:
    """ノードの鍵ペアを読み込み、無ければ生成して保存する。

    TWINLINK_KEYRING_SERVICE設定時はKeychainへ保存する。未設定のCLIデモでは
    Raw 32バイトを data_dir/keys/node_ed25519.key（0700/0600）へ保存する。
    """
    keys_dir = data_dir / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(keys_dir, 0o700)
    key_path = keys_dir / _KEY_FILENAME

    keyring_service = os.environ.get("TWINLINK_KEYRING_SERVICE", "").strip()
    if keyring_service:
        return _ensure_keyring_keypair(keyring_service, key_path)

    if key_path.exists():
        private_key = Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())
    else:
        private_key = Ed25519PrivateKey.generate()
        key_path.write_bytes(private_key.private_bytes_raw())
        os.chmod(key_path, 0o600)

    return _identity_from_private(private_key), private_key
