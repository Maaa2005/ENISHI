"""インメモリメールボックス（enishi.md §25 Relay Serverの責務 v2）。

配送のみを行い、本文を改変しない。TTL経過後のメッセージは
put/fetch時に遅延削除する。ack前のメッセージは再取得できる（再配送許容）。
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StoredMessage:
    delivery_id: str
    envelope: dict[str, Any]
    stored_at: float


@dataclass
class MailboxStore:
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
