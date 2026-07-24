import stat
from pathlib import Path

import pytest
from relay.database_tool import (
    DatabaseToolError,
    backup_database,
    restore_database,
    verify_database,
)
from relay.store import SqliteMailboxStore


def test_backup_and_restore_preserve_pending_delivery(tmp_path: Path) -> None:
    source = tmp_path / "relay.db"
    backup = tmp_path / "backups" / "relay.backup.db"
    restored = tmp_path / "restored" / "relay.db"
    store = SqliteMailboxStore(source)
    delivery_id = store.put("agt_receiver", {"message_id": "backup-proof"})

    backup_database(source, backup)
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert store.ack("agt_receiver", delivery_id) is True

    restore_database(backup, restored)
    restored_store = SqliteMailboxStore(restored)
    messages = restored_store.fetch("agt_receiver").items
    assert [message.delivery_id for message in messages] == [delivery_id]
    assert messages[0].envelope["message_id"] == "backup-proof"


def test_verify_rejects_corrupt_or_wrong_database(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not sqlite")
    with pytest.raises(DatabaseToolError, match="valid Relay SQLite"):
        verify_database(corrupt)

    empty = tmp_path / "empty.db"
    empty.touch()
    with pytest.raises(DatabaseToolError, match="missing Relay tables"):
        verify_database(empty)


def test_restore_requires_explicit_overwrite_and_clean_shutdown(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    destination = tmp_path / "destination.db"
    SqliteMailboxStore(source).put("agt_receiver", {"message_id": "m1"})
    backup_database(source, backup)
    destination.touch()

    with pytest.raises(DatabaseToolError, match="--force"):
        restore_database(backup, destination)

    wal = Path(f"{destination}-wal")
    wal.touch()
    with pytest.raises(DatabaseToolError, match="stop Relay cleanly"):
        restore_database(backup, destination, force=True)
    wal.unlink()

    restore_database(backup, destination, force=True)
    verify_database(destination)
