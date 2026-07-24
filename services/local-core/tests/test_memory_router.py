from pathlib import Path

import pytest
from enishi_core.config import get_settings
from enishi_core.models import Base, MemoryBackendStatus, MemoryItem, MemoryStatus
from enishi_core.services import memory_router, second_brain
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _configure_discovery(
    monkeypatch: pytest.MonkeyPatch, home: Path, *, enabled: bool
) -> None:
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(
        "ENISHI_AUTO_DISCOVER_EXTERNAL_MEMORY", "true" if enabled else "false"
    )
    get_settings.cache_clear()


def test_external_brain_is_auto_detected_and_receives_durable_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    (vault / "existing.md").write_text("# Existing\n", encoding="utf-8")
    _configure_discovery(monkeypatch, tmp_path, enabled=True)

    with _session() as session:
        user = second_brain.ensure_local_user(session)
        saved = second_brain.remember(
            session,
            user_id=user.id,
            title="外部脳を正本にする",
            text="既存のVaultがある場合はVaultへ保存する",
            memory_type="decision",
        )
        backend = memory_router.summary(session, user_id=user.id)

        assert saved.source_type == "obsidian"
        assert backend["status"] == MemoryBackendStatus.EXTERNAL_PRIMARY.value
        assert backend["detected_automatically"] is True
        assert list((vault / "Decisions").glob("*外部脳を正本にする*.md"))

    get_settings.cache_clear()


def test_search_refreshes_index_from_detected_external_brain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    (vault / "preference.md").write_text(
        "# 返答方針\n日本語で簡潔に返答する",
        encoding="utf-8",
    )
    _configure_discovery(monkeypatch, tmp_path, enabled=True)

    with _session() as session:
        user = second_brain.ensure_local_user(session)
        results = second_brain.search(
            session,
            user_id=user.id,
            query="簡潔",
        )
        backend = memory_router.summary(session, user_id=user.id)

        assert [item.title for item in results] == ["返答方針"]
        assert results[0].source_type == "obsidian"
        assert backend["last_synced_at"] is not None

    get_settings.cache_clear()


def test_external_disconnect_queues_writes_without_switching_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    (vault / "existing.md").write_text("# Existing\n", encoding="utf-8")
    _configure_discovery(monkeypatch, tmp_path, enabled=True)

    with _session() as session:
        user = second_brain.ensure_local_user(session)
        memory_router.resolve_backend(session, user_id=user.id)
        vault.rename(tmp_path / "Vault-offline")

        saved = second_brain.remember(
            session,
            user_id=user.id,
            title="切断中の判断",
            text="復旧後に外部脳へ同期する",
            memory_type="decision",
        )
        backend = memory_router.summary(session, user_id=user.id)

        assert saved.source_type == memory_router.PENDING_SOURCE
        assert backend["primary_source"] == "obsidian"
        assert backend["status"] == MemoryBackendStatus.EXTERNAL_UNAVAILABLE.value
        assert backend["pending_count"] == 1

    get_settings.cache_clear()


def test_internal_memories_can_migrate_after_external_brain_appears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_discovery(monkeypatch, tmp_path, enabled=False)
    with _session() as session:
        user = second_brain.ensure_local_user(session)
        original = second_brain.remember(
            session,
            user_id=user.id,
            title="移行対象",
            text="最初はENISHIが正本",
            memory_type="decision",
        )
        assert original.source_type == "enishi_mcp"
        legacy_project = second_brain.remember(
            session,
            user_id=user.id,
            title="旧形式のプロジェクト状態",
            text="project_stateも外部正本へ移行する",
            memory_type="project_state",
        )
        assert legacy_project.source_type == "enishi_mcp"

        vault = tmp_path / "Vault"
        vault.mkdir()
        (vault / "existing.md").write_text("# Existing\n", encoding="utf-8")
        _configure_discovery(monkeypatch, tmp_path, enabled=True)

        before = memory_router.summary(session, user_id=user.id)
        result = memory_router.migrate_to_external(session, user_id=user.id)
        session.refresh(original)
        session.refresh(legacy_project)
        indexed = list(
            session.scalars(
                select(MemoryItem).where(
                    MemoryItem.user_id == user.id,
                    MemoryItem.source_type == "obsidian",
                    MemoryItem.title == "移行対象",
                )
            )
        )

        assert before["status"] == MemoryBackendStatus.MIGRATING.value
        assert result == {
            "migrated": 2,
            "failed": 0,
            "pending": 0,
            "status": MemoryBackendStatus.EXTERNAL_PRIMARY.value,
        }
        assert original.status == MemoryStatus.DELETED.value
        assert legacy_project.status == MemoryStatus.DELETED.value
        assert len(indexed) == 1
        assert list((vault / "Projects").glob("*旧形式のプロジェクト状態*.md"))

    get_settings.cache_clear()
