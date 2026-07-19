"""Relay SQLiteメールボックスの安全なbackup・verify・restore CLI。"""

import argparse
import os
import sqlite3
import uuid
from pathlib import Path

REQUIRED_TABLES = {"messages", "rate_limits"}


class DatabaseToolError(RuntimeError):
    pass


def _readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise DatabaseToolError(f"database not found: {path}")
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=5.0)


def verify_database(path: str | Path) -> None:
    database = Path(path)
    try:
        with _readonly_connection(database) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise DatabaseToolError("database integrity check failed")
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
    except sqlite3.DatabaseError as exc:
        raise DatabaseToolError("database is not a valid Relay SQLite database") from exc
    missing = REQUIRED_TABLES - tables
    if missing:
        raise DatabaseToolError(
            f"database is missing Relay tables: {','.join(sorted(missing))}"
        )


def _copy_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        with _readonly_connection(source) as source_connection:
            with sqlite3.connect(temporary) as destination_connection:
                source_connection.backup(destination_connection)
        verify_database(temporary)
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def backup_database(source: str | Path, destination: str | Path) -> Path:
    source_path = Path(source)
    destination_path = Path(destination)
    if destination_path.exists():
        raise DatabaseToolError(f"backup already exists: {destination_path}")
    verify_database(source_path)
    _copy_database(source_path, destination_path)
    return destination_path


def restore_database(
    backup: str | Path, destination: str | Path, *, force: bool = False
) -> Path:
    backup_path = Path(backup)
    destination_path = Path(destination)
    verify_database(backup_path)
    sidecars = [
        Path(f"{destination_path}-wal"),
        Path(f"{destination_path}-shm"),
    ]
    if any(path.exists() for path in sidecars):
        raise DatabaseToolError(
            "database WAL/SHM files exist; stop Relay cleanly before restore"
        )
    if destination_path.exists() and not force:
        raise DatabaseToolError("destination exists; pass --force after stopping Relay")
    _copy_database(backup_path, destination_path)
    return destination_path


def main() -> None:
    parser = argparse.ArgumentParser(description="ENISHI Relay database operations")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--database", required=True)
    backup_parser.add_argument("--output", required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--database", required=True)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", required=True)
    restore_parser.add_argument("--database", required=True)
    restore_parser.add_argument("--force", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "backup":
            result = backup_database(args.database, args.output)
            print(f"backup verified: {result}")
        elif args.command == "verify":
            verify_database(args.database)
            print(f"database verified: {args.database}")
        else:
            result = restore_database(args.backup, args.database, force=args.force)
            print(f"restore verified: {result}")
    except DatabaseToolError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
