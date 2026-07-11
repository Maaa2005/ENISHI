"""ノード鍵ペア管理（twinlink.md §25 信頼モデル v2）。

Agent IDはEd25519公開鍵から導出する。

注意: §9では秘密鍵はKeychainへ保存する。Rust側のKeychainラッパーが
未導入のため、デモ暫定としてファイル保存（0600）とし、
Tauri Keychain実装後に移行する。
"""

import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel

_KEY_FILENAME = "node_ed25519.key"


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


def ensure_node_keypair(data_dir: Path) -> tuple[NodeIdentity, Ed25519PrivateKey]:
    """ノードの鍵ペアを読み込み、無ければ生成して保存する。

    秘密鍵はRaw 32バイトで data_dir/keys/node_ed25519.key へ保存する
    （ディレクトリ0700・ファイル0600）。
    """
    keys_dir = data_dir / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(keys_dir, 0o700)
    key_path = keys_dir / _KEY_FILENAME

    if key_path.exists():
        private_key = Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())
    else:
        private_key = Ed25519PrivateKey.generate()
        key_path.write_bytes(private_key.private_bytes_raw())
        os.chmod(key_path, 0o600)

    return _identity_from_private(private_key), private_key
