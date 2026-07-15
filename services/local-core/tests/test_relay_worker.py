import asyncio
from types import SimpleNamespace
from typing import Any

from twinlink_core.services import relay_worker


class _Session:
    def __init__(self) -> None:
        self.closed = False
        self.rolled_back = False

    def close(self) -> None:
        self.closed = True

    def rollback(self) -> None:
        self.rolled_back = True


async def test_worker_without_relay_waits_and_stops(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        relay_worker,
        "get_settings",
        lambda: SimpleNamespace(
            relay_url="",
            relay_token="",
            relay_poll_interval_seconds=0.01,
            relay_poll_backoff_max_seconds=0.02,
        ),
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(relay_worker.worker_loop(stop_event))
    await asyncio.sleep(0)
    assert relay_worker.status()["running"] is True

    stop_event.set()
    await asyncio.wait_for(task, timeout=0.2)
    assert relay_worker.status()["running"] is False


async def test_worker_polls_once_and_closes_session(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        relay_worker,
        "get_settings",
        lambda: SimpleNamespace(
            relay_url="https://relay.invalid",
            relay_token="token",
            relay_poll_interval_seconds=0.01,
            relay_poll_backoff_max_seconds=0.02,
        ),
    )
    session = _Session()
    stop_event = asyncio.Event()
    calls: list[object] = []

    monkeypatch.setattr(relay_worker, "get_session", lambda: iter([session]))
    monkeypatch.setattr(relay_worker, "get_relay_client", lambda: object())

    def sync_once(current_session: object, relay: object) -> dict[str, object]:
        calls.append(relay)
        assert current_session is session
        stop_event.set()
        return {"processed": 0}

    monkeypatch.setattr(relay_worker, "sync_session", sync_once)

    await asyncio.wait_for(relay_worker.worker_loop(stop_event), timeout=0.2)

    assert len(calls) == 1
    assert session.closed is True
    assert session.rolled_back is False
    assert relay_worker.status()["running"] is False
