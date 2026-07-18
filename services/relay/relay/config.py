"""Relay設定。環境変数 RELAY_* から読み込む。"""

import hashlib
import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class RelaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELAY_")

    # "agentA=tok1,agentB=tok2" 形式の事前共有トークン（デモ用、§25）
    node_tokens: str = ""
    # "agentA=<sha256>,agentB=<sha256>"。同一agentを複数回書けばローテーション可能。
    node_token_hashes: str = ""
    # 本番では平文設定を拒否し、node_token_hashesを必須にする。
    require_hashed_tokens: bool = False
    message_ttl_seconds: int = 3600
    max_message_bytes: int = 65536
    rate_limit_per_minute: int = 120
    # 空ならインメモリ。運用・デモではSQLiteファイルを明示する。
    database_path: str = ""

    @staticmethod
    def _credential_entries(raw: str, setting_name: str) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = []
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if "=" not in entry:
                raise ValueError(f"{setting_name}の形式が不正です。")
            agent_id, credential = (part.strip() for part in entry.split("=", 1))
            if not agent_id or not credential:
                raise ValueError(f"{setting_name}に空のagent_idまたはcredentialがあります。")
            entries.append((agent_id, credential))
        return entries

    def plaintext_credentials(self) -> list[tuple[str, str]]:
        return self._credential_entries(self.node_tokens, "RELAY_NODE_TOKENS")

    def hashed_credentials(self) -> list[tuple[str, str]]:
        entries = self._credential_entries(
            self.node_token_hashes, "RELAY_NODE_TOKEN_HASHES"
        )
        normalized: list[tuple[str, str]] = []
        for agent_id, digest in entries:
            digest = digest.lower()
            try:
                decoded = bytes.fromhex(digest)
            except ValueError as exc:
                raise ValueError(
                    "RELAY_NODE_TOKEN_HASHESにはSHA-256のhex値が必要です。"
                ) from exc
            if len(decoded) != hashlib.sha256().digest_size:
                raise ValueError(
                    "RELAY_NODE_TOKEN_HASHESにはSHA-256のhex値が必要です。"
                )
            normalized.append((agent_id, digest))
        return normalized

    def validate_auth_configuration(self) -> None:
        plaintext = self.plaintext_credentials()
        hashed = self.hashed_credentials()
        if self.require_hashed_tokens and plaintext:
            raise ValueError(
                "RELAY_REQUIRE_HASHED_TOKENS=trueではRELAY_NODE_TOKENSを使用できません。"
            )
        if self.require_hashed_tokens and not hashed:
            raise ValueError(
                "RELAY_REQUIRE_HASHED_TOKENS=trueではRELAY_NODE_TOKEN_HASHESが必要です。"
            )

        owners: dict[str, str] = {}
        fingerprints = [
            (agent_id, hashlib.sha256(token.encode("utf-8")).hexdigest())
            for agent_id, token in plaintext
        ] + hashed
        for agent_id, fingerprint in fingerprints:
            previous = owners.setdefault(fingerprint, agent_id)
            if previous != agent_id:
                raise ValueError("同じRelay credentialを複数agentへ割り当てられません。")

    def authenticate(self, provided: str) -> str | None:
        """全credentialを定数時間比較し、一致するagent_idを返す。"""
        if not provided:
            return None
        provided_hash = hashlib.sha256(provided.encode("utf-8")).hexdigest()
        matches: set[str] = set()
        for agent_id, token in self.plaintext_credentials():
            if secrets.compare_digest(provided, token):
                matches.add(agent_id)
        for agent_id, token_hash in self.hashed_credentials():
            if secrets.compare_digest(provided_hash, token_hash):
                matches.add(agent_id)
        if len(matches) != 1:
            return None
        return next(iter(matches))

    def auth_mode(self) -> str:
        has_plaintext = bool(self.plaintext_credentials())
        has_hashes = bool(self.hashed_credentials())
        if has_plaintext and has_hashes:
            return "mixed"
        if has_hashes:
            return "hashed"
        if has_plaintext:
            return "plaintext"
        return "unconfigured"

    def known_agents(self) -> set[str]:
        return {
            agent_id
            for agent_id, _ in self.plaintext_credentials() + self.hashed_credentials()
        }


@lru_cache
def get_relay_settings() -> RelaySettings:
    return RelaySettings()
