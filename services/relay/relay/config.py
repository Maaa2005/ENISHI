"""Relay設定。環境変数 RELAY_* から読み込む。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class RelaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELAY_")

    # "agentA=tok1,agentB=tok2" 形式の事前共有トークン（デモ用、§25）
    node_tokens: str = ""
    message_ttl_seconds: int = 3600
    max_message_bytes: int = 65536
    rate_limit_per_minute: int = 120

    def token_map(self) -> dict[str, str]:
        """トークン→agent_id の対応表を返す。"""
        mapping: dict[str, str] = {}
        for entry in self.node_tokens.split(","):
            entry = entry.strip()
            if not entry or "=" not in entry:
                continue
            agent_id, token = entry.split("=", 1)
            mapping[token.strip()] = agent_id.strip()
        return mapping

    def known_agents(self) -> set[str]:
        return set(self.token_map().values())


@lru_cache
def get_relay_settings() -> RelaySettings:
    return RelaySettings()
