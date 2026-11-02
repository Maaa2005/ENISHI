"""テスト共通設定。一時ディレクトリのSQLiteを使い、本番データに触れない。"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_TOKEN = "test-local-token"


@pytest.fixture(autouse=True)
def _isolated_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """全テストで実ホームを触らない。

    Windowsの Path.home() は HOME ではなく USERPROFILE（なければ HOMEDRIVE+HOMEPATH）を
    参照するため、HOME だけの差し替えでは実ユーザーの Vault 等へ書き込んでしまう。
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOMEDRIVE", home.drive)
    monkeypatch.setenv("HOMEPATH", str(home)[len(home.drive) :])
    return home


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ENISHI_LOCAL_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("ENISHI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ENISHI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("ENISHI_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ENISHI_TASK_WORKER_POLL_INTERVAL_SECONDS", "0.01")
    monkeypatch.setenv("ENISHI_MOCK_TASK_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("ENISHI_AUTO_DISCOVER_EXTERNAL_MEMORY", "false")

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
