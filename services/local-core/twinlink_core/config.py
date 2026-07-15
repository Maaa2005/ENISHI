"""設定。環境変数 TWINLINK_* から読み込む。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TWINLINK_")

    # Tauriが起動時に生成して渡すローカル認証トークン。
    # 空のままでは /v1/* へアクセスできない（開発時は .env で設定する）。
    local_token: str = ""
    local_port: int = 8765

    # Relay Server接続設定（twinlink.md §25, §26）。空ならRelay機能は無効
    relay_url: str = ""
    relay_token: str = ""
    relay_poll_interval_seconds: float = 2.0
    relay_poll_backoff_max_seconds: float = 60.0

    approval_ttl_seconds: int = 3600
    task_timeout_seconds: int = 600
    codex_task_timeout_seconds: int | None = None
    claude_code_task_timeout_seconds: int | None = None
    mock_task_timeout_seconds: int | None = None
    task_worker_poll_interval_seconds: float = 0.5
    task_worker_id: str = "local-core-worker-1"

    data_dir: Path = Path.home() / "Library" / "Application Support" / "TwinLink"
    cache_dir: Path = Path.home() / "Library" / "Caches" / "TwinLink"
    log_dir: Path = Path.home() / "Library" / "Logs" / "TwinLink"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'twinlink.db'}"

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.cache_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def timeout_for_provider(self, provider: str) -> int:
        provider_timeout = {
            "codex": self.codex_task_timeout_seconds,
            "claude_code": self.claude_code_task_timeout_seconds,
            "mock": self.mock_task_timeout_seconds,
        }.get(provider)
        return provider_timeout or self.task_timeout_seconds


@lru_cache
def get_settings() -> Settings:
    return Settings()
