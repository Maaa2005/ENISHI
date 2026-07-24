import pytest
from enishi_core.config import Settings
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("local_port", 0),
        ("relay_poll_interval_seconds", 0),
        ("approval_ttl_seconds", 0),
        ("task_timeout_seconds", -1),
        ("codex_task_timeout_seconds", 0),
    ],
)
def test_positive_settings_fail_fast(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_relay_backoff_must_cover_poll_interval() -> None:
    with pytest.raises(ValidationError, match="backoff"):
        Settings(
            relay_poll_interval_seconds=10,
            relay_poll_backoff_max_seconds=5,
        )


def test_remote_relay_requires_https() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(relay_url="http://relay.example.com")
    assert Settings(relay_url="http://127.0.0.1:8870").relay_url.startswith("http://")


def test_provider_timeout_none_inherits_default() -> None:
    settings = Settings(task_timeout_seconds=42, codex_task_timeout_seconds=None)
    assert settings.timeout_for_provider("codex") == 42
