"""Relayメールボックス（enishi.md §25 Relay Serverの責務 v2）。

配送のみを行い、本文を改変しない。TTL経過後のメッセージは
put/fetch時に遅延削除する。ack前のメッセージは再取得できる（再配送許容）。
本番向けにはSQLite、単体テスト向けにはインメモリ実装を提供する。
"""

import binascii
import json
import sqlite3
import time
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class StoredMessage:
    delivery_id: str
    envelope: dict[str, Any]
    stored_at: float


@dataclass(frozen=True)
class MailboxPage:
    items: list[StoredMessage]
    next_cursor: str | None


class MailboxCapacityExceeded(Exception):
    def __init__(self, scope: str) -> None:
        super().__init__(scope)
        self.scope = scope


def _encode_cursor(message: StoredMessage) -> str:
    raw = json.dumps(
        [message.stored_at, message.delivery_id], separators=(",", ":")
    ).encode("utf-8")
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[float, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(urlsafe_b64decode(padded).decode("utf-8"))
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not isinstance(value[0], (int, float))
            or not isinstance(value[1], str)
        ):
            raise ValueError
        return float(value[0]), value[1]
    except (
        ValueError,
        TypeError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("invalid mailbox cursor") from exc


class MailboxBackend(Protocol):
    """FastAPI層から利用するメールボックスの最小インターフェース。"""

    backend_name: str

    def allow_send(self, sender: str) -> bool: ...

    def put(self, receiver: str, envelope: dict[str, Any], size: int) -> str: ...

    def fetch(self, receiver: str, limit: int, cursor: str | None) -> MailboxPage: ...

    def ack(self, receiver: str, delivery_id: str) -> bool: ...

    def check_ready(self) -> None: ...

    def pending_stats(self) -> tuple[int, int]: ...


@dataclass
class MailboxStore:
    backend_name = "memory"

    ttl_seconds: int = 3600
    rate_limit_per_minute: int = 120
    max_pending_messages_per_receiver: int = 1000
    max_pending_bytes_per_receiver: int = 64 * 1024 * 1024
    max_total_pending_bytes: int = 512 * 1024 * 1024
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

    def put(self, receiver: str, envelope: dict[str, Any], size: int | None = None) -> str:
        self._purge()
        serialized_size = size if size is not None else len(
            json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        receiver_messages = self._mailboxes.get(receiver, [])
        receiver_bytes = sum(
            len(
                json.dumps(message.envelope, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            for message in receiver_messages
        )
        total_bytes = self.pending_stats()[1]
        if len(receiver_messages) >= self.max_pending_messages_per_receiver:
            raise MailboxCapacityExceeded("receiver_messages")
        if receiver_bytes + serialized_size > self.max_pending_bytes_per_receiver:
            raise MailboxCapacityExceeded("receiver_bytes")
        if total_bytes + serialized_size > self.max_total_pending_bytes:
            raise MailboxCapacityExceeded("total_bytes")
        delivery_id = uuid.uuid4().hex
        self._mailboxes.setdefault(receiver, []).append(
            StoredMessage(
                delivery_id=delivery_id,
                envelope=envelope,
                stored_at=float(self.clock()),
            )
        )
        return delivery_id

    def fetch(
        self, receiver: str, limit: int = 50, cursor: str | None = None
    ) -> MailboxPage:
        """ack前のメッセージ一覧を返す（再取得可能=再配送許容）。"""
        self._purge()
        messages = sorted(
            self._mailboxes.get(receiver, []),
            key=lambda message: (message.stored_at, message.delivery_id),
        )
        if cursor:
            cursor_key = _decode_cursor(cursor)
            messages = [
                message
                for message in messages
                if (message.stored_at, message.delivery_id) > cursor_key
            ]
        page_items = messages[:limit]
        next_cursor = (
            _encode_cursor(page_items[-1]) if len(messages) > len(page_items) else None
        )
        return MailboxPage(items=list(page_items), next_cursor=next_cursor)

    def ack(self, receiver: str, delivery_id: str) -> bool:
        messages = self._mailboxes.get(receiver, [])
        remaining = [m for m in messages if m.delivery_id != delivery_id]
        if len(remaining) == len(messages):
            return False
        self._mailboxes[receiver] = remaining
        return True

    def check_ready(self) -> None:
        """インメモリ実装は生成済みなら常に利用可能。"""

    def pending_stats(self) -> tuple[int, int]:
        self._purge()
        messages = [message for items in self._mailboxes.values() for message in items]
        pending_bytes = sum(
            len(
                json.dumps(message.envelope, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            for message in messages
        )
        return len(messages), pending_bytes


@dataclass
class SqliteMailboxStore:
    """再起動後も未ack配送とレート制限を保持するSQLite実装。"""

    database_path: str | Path
    ttl_seconds: int = 3600
    rate_limit_per_minute: int = 120
    max_pending_messages_per_receiver: int = 1000
    max_pending_bytes_per_receiver: int = 64 * 1024 * 1024
    max_total_pending_bytes: int = 512 * 1024 * 1024
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
                    stored_at REAL NOT NULL,
                    envelope_bytes INTEGER NOT NULL DEFAULT 0
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
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "envelope_bytes" not in columns:
                connection.execute(
                    "ALTER TABLE messages ADD COLUMN envelope_bytes INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                "UPDATE messages SET envelope_bytes = length(CAST(envelope_json AS BLOB)) "
                "WHERE envelope_bytes = 0"
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

    def put(self, receiver: str, envelope: dict[str, Any], size: int | None = None) -> str:
        delivery_id = uuid.uuid4().hex
        now = float(self.clock())
        serialized = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        serialized_size = size if size is not None else len(serialized.encode("utf-8"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._purge_messages(connection, now)
            receiver_count, receiver_bytes = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(envelope_bytes), 0) "
                "FROM messages WHERE receiver = ?",
                (receiver,),
            ).fetchone()
            total_bytes = connection.execute(
                "SELECT COALESCE(SUM(envelope_bytes), 0) FROM messages"
            ).fetchone()[0]
            if int(receiver_count) >= self.max_pending_messages_per_receiver:
                raise MailboxCapacityExceeded("receiver_messages")
            if int(receiver_bytes) + serialized_size > self.max_pending_bytes_per_receiver:
                raise MailboxCapacityExceeded("receiver_bytes")
            if int(total_bytes) + serialized_size > self.max_total_pending_bytes:
                raise MailboxCapacityExceeded("total_bytes")
            connection.execute(
                """
                INSERT INTO messages(
                    delivery_id, receiver, envelope_json, stored_at, envelope_bytes
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (delivery_id, receiver, serialized, now, serialized_size),
            )
        return delivery_id

    def fetch(
        self, receiver: str, limit: int = 50, cursor: str | None = None
    ) -> MailboxPage:
        now = float(self.clock())
        cursor_key = _decode_cursor(cursor) if cursor else None
        with self._connect() as connection:
            self._purge_messages(connection, now)
            if cursor_key is None:
                rows = connection.execute(
                    """
                    SELECT delivery_id, envelope_json, stored_at
                    FROM messages
                    WHERE receiver = ?
                    ORDER BY stored_at, delivery_id
                    LIMIT ?
                    """,
                    (receiver, limit + 1),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT delivery_id, envelope_json, stored_at
                    FROM messages
                    WHERE receiver = ?
                      AND (stored_at > ? OR (stored_at = ? AND delivery_id > ?))
                    ORDER BY stored_at, delivery_id
                    LIMIT ?
                    """,
                    (receiver, cursor_key[0], cursor_key[0], cursor_key[1], limit + 1),
                ).fetchall()
        items = [
            StoredMessage(
                delivery_id=str(row[0]),
                envelope=json.loads(str(row[1])),
                stored_at=float(row[2]),
            )
            for row in rows[:limit]
        ]
        return MailboxPage(
            items=items,
            next_cursor=_encode_cursor(items[-1]) if len(rows) > limit and items else None,
        )

    def ack(self, receiver: str, delivery_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM messages WHERE receiver = ? AND delivery_id = ?",
                (receiver, delivery_id),
            )
        return cursor.rowcount > 0

    def check_ready(self) -> None:
        """DBへ書き込みtransactionを開始でき、mailboxを読めることを確認する。"""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("SELECT COUNT(*) FROM messages").fetchone()
            connection.rollback()

    def pending_stats(self) -> tuple[int, int]:
        now = float(self.clock())
        with self._connect() as connection:
            self._purge_messages(connection, now)
            row = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(envelope_bytes), 0) FROM messages"
            ).fetchone()
        return (int(row[0]), int(row[1])) if row is not None else (0, 0)
