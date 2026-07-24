"""設定。環境変数 ENISHI_* から読み込む。"""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENISHI_")

    # Tauriが起動時に生成して渡すローカル認証トークン。
    # 空のままでは /v1/* へアクセスできない（開発時は .env で設定する）。
    local_token: str = ""
    local_port: int = Field(default=8765, ge=1, le=65535)

    # Relay Server接続設定（enishi.md §25, §26）。空ならRelay機能は無効
    relay_url: str = ""
    relay_token: str = ""
    relay_poll_interval_seconds: float = Field(default=2.0, gt=0)
    relay_poll_backoff_max_seconds: float = Field(default=60.0, gt=0)

    approval_ttl_seconds: int = Field(default=3600, gt=0)
    task_timeout_seconds: int = Field(default=600, gt=0)
    codex_task_timeout_seconds: int | None = Field(default=None, gt=0)
    claude_code_task_timeout_seconds: int | None = Field(default=None, gt=0)
    mock_task_timeout_seconds: int | None = Field(default=None, gt=0)
    task_worker_poll_interval_seconds: float = Field(default=0.5, gt=0)
    task_worker_id: str = "local-core-worker-1"
    auto_discover_external_memory: bool = True

    data_dir: Path = Path.home() / "Library" / "Application Support" / "ENISHI"
    cache_dir: Path = Path.home() / "Library" / "Caches" / "ENISHI"
    log_dir: Path = Path.home() / "Library" / "Logs" / "ENISHI"

    @model_validator(mode="after")
    def validate_relay_settings(self) -> "Settings":
        if self.relay_poll_backoff_max_seconds < self.relay_poll_interval_seconds:
            raise ValueError(
                "relay_poll_backoff_max_seconds must be greater than or equal to "
                "relay_poll_interval_seconds"
            )
        if self.relay_url:
            parsed = urlparse(self.relay_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("relay_url must be an absolute HTTP(S) URL")
            if parsed.scheme != "https" and parsed.hostname not in {
                "127.0.0.1",
                "localhost",
                "::1",
            }:
                raise ValueError("non-loopback relay_url must use HTTPS")
        return self

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'enishi.db'}"

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.cache_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def timeout_for_provider(self, provider: str) -> int:
        provider_timeout = {
            "codex": self.codex_task_timeout_seconds,
            "claude_code": self.claude_code_task_timeout_seconds,
            "mock": self.mock_task_timeout_seconds,
        }.get(provider)
        return (
            provider_timeout
            if provider_timeout is not None
            else self.task_timeout_seconds
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
