"""Relayテスト共通設定。事前共有トークン2ノード構成。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from relay.config import get_relay_settings

TOKEN_A = "token-a"
TOKEN_B = "token-b"
AGENT_A = "agt_aaaa"
AGENT_B = "agt_bbbb"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("RELAY_NODE_TOKENS", f"{AGENT_A}={TOKEN_A},{AGENT_B}={TOKEN_B}")
    monkeypatch.setenv("RELAY_MAX_MESSAGE_BYTES", "2048")
    monkeypatch.setenv("RELAY_RATE_LIMIT_PER_MINUTE", "5")
    monkeypatch.delenv("RELAY_DATABASE_PATH", raising=False)
    monkeypatch.delenv("RELAY_NODE_TOKEN_HASHES", raising=False)
    monkeypatch.delenv("RELAY_REQUIRE_HASHED_TOKENS", raising=False)
    monkeypatch.delenv("RELAY_DOCS_ENABLED", raising=False)
    get_relay_settings.cache_clear()

    from relay.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_relay_settings.cache_clear()


@pytest.fixture()
def headers_a() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN_A}"}


@pytest.fixture()
def headers_b() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN_B}"}
