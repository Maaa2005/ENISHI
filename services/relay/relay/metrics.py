"""秘密情報を含まないRelay運用メトリクス。"""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RelayMetrics:
    clock: Any = time.monotonic
    started_at: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _deliveries: int = 0
    _fetched: int = 0
    _acknowledged: int = 0
    _readiness_failures: int = 0
    _rejections: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def __post_init__(self) -> None:
        self.started_at = float(self.clock())

    def delivered(self) -> None:
        with self._lock:
            self._deliveries += 1

    def fetched(self, count: int) -> None:
        with self._lock:
            self._fetched += count

    def acknowledged(self) -> None:
        with self._lock:
            self._acknowledged += 1

    def rejected(self, code: str) -> None:
        with self._lock:
            self._rejections[code] += 1

    def readiness_failed(self) -> None:
        with self._lock:
            self._readiness_failures += 1

    def render(self, pending_messages: int, pending_bytes: int) -> str:
        with self._lock:
            deliveries = self._deliveries
            fetched = self._fetched
            acknowledged = self._acknowledged
            readiness_failures = self._readiness_failures
            rejections = sorted(self._rejections.items())
        uptime = max(0.0, float(self.clock()) - self.started_at)
        lines = [
            "# HELP enishi_relay_uptime_seconds Relay process uptime.",
            "# TYPE enishi_relay_uptime_seconds gauge",
            f"enishi_relay_uptime_seconds {uptime:.3f}",
            "# HELP enishi_relay_pending_messages Current unacknowledged deliveries.",
            "# TYPE enishi_relay_pending_messages gauge",
            f"enishi_relay_pending_messages {pending_messages}",
            "# HELP enishi_relay_pending_bytes Current unacknowledged delivery bytes.",
            "# TYPE enishi_relay_pending_bytes gauge",
            f"enishi_relay_pending_bytes {pending_bytes}",
            "# HELP enishi_relay_deliveries_total Accepted deliveries.",
            "# TYPE enishi_relay_deliveries_total counter",
            f"enishi_relay_deliveries_total {deliveries}",
            "# HELP enishi_relay_fetched_messages_total Messages returned by fetch calls.",
            "# TYPE enishi_relay_fetched_messages_total counter",
            f"enishi_relay_fetched_messages_total {fetched}",
            "# HELP enishi_relay_acknowledged_total Acknowledged deliveries.",
            "# TYPE enishi_relay_acknowledged_total counter",
            f"enishi_relay_acknowledged_total {acknowledged}",
            "# HELP enishi_relay_readiness_failures_total Failed readiness checks.",
            "# TYPE enishi_relay_readiness_failures_total counter",
            f"enishi_relay_readiness_failures_total {readiness_failures}",
            "# HELP enishi_relay_rejections_total Rejected Relay operations by code.",
            "# TYPE enishi_relay_rejections_total counter",
        ]
        lines.extend(
            f'enishi_relay_rejections_total{{code="{code}"}} {count}'
            for code, count in rejections
        )
        return "\n".join(lines) + "\n"
