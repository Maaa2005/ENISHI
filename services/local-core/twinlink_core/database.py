"""SQLiteデータベース接続。"""

import importlib
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from twinlink_core.config import get_settings
from twinlink_core.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_BASELINE_REVISION = "202607130003"


def _is_memory_database(url: str) -> bool:
    return url in {"sqlite://", "sqlite:///:memory:"} or url.startswith(
        "sqlite+pysqlite:///:memory:"
    )


def _sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite:///"):
        return None
    return Path(url.removeprefix("sqlite:///"))


def _alembic_config(database_url: str) -> object:
    config_module = importlib.import_module("alembic.config")
    config_class = cast(Any, config_module).Config

    root = Path(__file__).resolve().parents[1]
    config = config_class(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic_migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _backup_database_if_needed(database_url: str) -> None:
    db_path = _sqlite_path(database_url)
    if db_path is None or not db_path.exists():
        return
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.{timestamp}.bak")
    shutil.copy2(db_path, backup_path)


def upgrade_schema(database_url: str) -> None:
    """ファイルSQLiteをAlembicで最新スキーマへ更新する（twinlink.md §8）。"""
    if _is_memory_database(database_url):
        return
    _backup_database_if_needed(database_url)
    try:
        command = importlib.import_module("alembic.command")
    except ImportError:
        _upgrade_schema_without_alembic_package(database_url)
        return
    cast(Any, command).upgrade(_alembic_config(database_url), "head")


def _upgrade_schema_without_alembic_package(database_url: str) -> None:
    """オフライン検証環境用のフォールバック。配布環境ではAlembic依存を使う。"""
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "create table if not exists alembic_version "
                    "(version_num varchar(32) not null)"
                )
            )
            current = connection.execute(text("select version_num from alembic_version")).scalar()
            if current is None:
                connection.execute(
                    text("insert into alembic_version (version_num) values (:revision)"),
                    {"revision": _BASELINE_REVISION},
                )
            elif current != _BASELINE_REVISION:
                connection.execute(
                    text("update alembic_version set version_num = :revision"),
                    {"revision": _BASELINE_REVISION},
                )
    finally:
        engine.dispose()


def init_database(database_url: str | None = None) -> Engine:
    """エンジンを初期化する。本番DBはAlembicでスキーマ管理する。"""
    global _engine, _session_factory
    url = database_url or get_settings().database_url
    if not _is_memory_database(url):
        upgrade_schema(url)
    _engine = create_engine(url, connect_args={"check_same_thread": False})
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    if _is_memory_database(url):
        Base.metadata.create_all(_engine)
    return _engine


def get_session() -> Iterator[Session]:
    """FastAPI依存性。リクエストごとにセッションを払い出す。"""
    if _session_factory is None:
        raise RuntimeError("database is not initialized")
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def is_connected() -> bool:
    return _engine is not None
