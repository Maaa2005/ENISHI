"""テスト共通設定。一時ディレクトリのSQLiteを使い、本番データに触れない。"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_TOKEN = "test-local-token"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ENISHI_LOCAL_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("ENISHI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ENISHI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("ENISHI_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ENISHI_TASK_WORKER_POLL_INTERVAL_SECONDS", "0.01")
    monkeypatch.setenv("ENISHI_MOCK_TASK_TIMEOUT_SECONDS", "2")

    from enishi_core.config import get_settings

    get_settings.cache_clear()

    from enishi_core.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}
