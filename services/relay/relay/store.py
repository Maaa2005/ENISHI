"""Relayメールボックス（enishi.md §25 Relay Serverの責務 v2）。

配送のみを行い、本文を改変しない。TTL経過後のメッセージは
put/fetch時に遅延削除する。ack前のメッセージは再取得できる（再配送許容）。
本番向けにはSQLite、単体テスト向けにはインメモリ実装を提供する。
"""

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class StoredMessage:
    delivery_id: str
    envelope: dict[str, Any]
    stored_at: float


class MailboxBackend(Protocol):
    """FastAPI層から利用するメールボックスの最小インターフェース。"""

    backend_name: str

    def allow_send(self, sender: str) -> bool: ...

    def put(self, receiver: str, envelope: dict[str, Any]) -> str: ...

    def fetch(self, receiver: str) -> list[StoredMessage]: ...

    def ack(self, receiver: str, delivery_id: str) -> bool: ...


@dataclass
class MailboxStore:
    backend_name = "memory"

    ttl_seconds: int = 3600
    rate_limit_per_minute: int = 120
    clock: Any = time.time

    _mailboxes: dict[str, list[StoredMessage]] = field(default_factory=dict)
    _rate: dict[tuple[str, int], int] = field(default_factory=dict)

    def _purge(self) -> None:
        now = float(self.clock())
        for receiver, messages in list(self._mailboxes.items()):
            kept = [m for m in messages if now - m.stored_at < self.ttl_seconds]
            self._mailboxes[receiver] = kept
        # レート制限カウンタも古い分を破棄する
        current_minute = int(now // 60)
        for key in list(self._rate):
            if key[1] < current_minute - 1:
                del self._rate[key]

    def allow_send(self, sender: str) -> bool:
        """送信者×分単位のレート制限を判定し、許可ならカウントする。"""
        now = float(self.clock())
        key = (sender, int(now // 60))
        count = self._rate.get(key, 0)
        if count >= self.rate_limit_per_minute:
            return False
        self._rate[key] = count + 1
        return True

    def put(self, receiver: str, envelope: dict[str, Any]) -> str:
        self._purge()
        delivery_id = uuid.uuid4().hex
        self._mailboxes.setdefault(receiver, []).append(
            StoredMessage(
                delivery_id=delivery_id,
                envelope=envelope,
                stored_at=float(self.clock()),
            )
        )
        return delivery_id

    def fetch(self, receiver: str) -> list[StoredMessage]:
        """ack前のメッセージ一覧を返す（再取得可能=再配送許容）。"""
        self._purge()
        return list(self._mailboxes.get(receiver, []))

    def ack(self, receiver: str, delivery_id: str) -> bool:
        messages = self._mailboxes.get(receiver, [])
        remaining = [m for m in messages if m.delivery_id != delivery_id]
        if len(remaining) == len(messages):
            return False
        self._mailboxes[receiver] = remaining
        return True


@dataclass
class SqliteMailboxStore:
    """再起動後も未ack配送とレート制限を保持するSQLite実装。"""

    database_path: str | Path
    ttl_seconds: int = 3600
    rate_limit_per_minute: int = 120
    clock: Any = time.time

    backend_name = "sqlite"

    def __post_init__(self) -> None:
        self.database_path = Path(self.database_path).expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    delivery_id TEXT PRIMARY KEY,
                    receiver TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    stored_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_receiver_stored
                    ON messages(receiver, stored_at);
                CREATE TABLE IF NOT EXISTS rate_limits (
                    sender TEXT NOT NULL,
                    minute_bucket INTEGER NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY(sender, minute_bucket)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _purge_messages(self, connection: sqlite3.Connection, now: float) -> None:
        connection.execute(
            "DELETE FROM messages WHERE stored_at <= ?",
            (now - self.ttl_seconds,),
        )

    def allow_send(self, sender: str) -> bool:
        now = float(self.clock())
        minute = int(now // 60)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM rate_limits WHERE minute_bucket < ?", (minute - 1,)
            )
            row = connection.execute(
                "SELECT count FROM rate_limits WHERE sender = ? AND minute_bucket = ?",
                (sender, minute),
            ).fetchone()
            count = int(row[0]) if row is not None else 0
            if count >= self.rate_limit_per_minute:
                return False
            connection.execute(
                """
                INSERT INTO rate_limits(sender, minute_bucket, count)
                VALUES (?, ?, 1)
                ON CONFLICT(sender, minute_bucket)
                DO UPDATE SET count = count + 1
                """,
                (sender, minute),
            )
        return True

    def put(self, receiver: str, envelope: dict[str, Any]) -> str:
        delivery_id = uuid.uuid4().hex
        now = float(self.clock())
        serialized = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            self._purge_messages(connection, now)
            connection.execute(
                """
                INSERT INTO messages(delivery_id, receiver, envelope_json, stored_at)
                VALUES (?, ?, ?, ?)
                """,
                (delivery_id, receiver, serialized, now),
            )
        return delivery_id

    def fetch(self, receiver: str) -> list[StoredMessage]:
        now = float(self.clock())
        with self._connect() as connection:
            self._purge_messages(connection, now)
            rows = connection.execute(
                """
                SELECT delivery_id, envelope_json, stored_at
                FROM messages
                WHERE receiver = ?
                ORDER BY stored_at, rowid
                """,
                (receiver,),
            ).fetchall()
        return [
            StoredMessage(
                delivery_id=str(row[0]),
                envelope=json.loads(str(row[1])),
                stored_at=float(row[2]),
            )
            for row in rows
        ]

    def ack(self, receiver: str, delivery_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM messages WHERE receiver = ? AND delivery_id = ?",
                (receiver, delivery_id),
            )
        return cursor.rowcount > 0
