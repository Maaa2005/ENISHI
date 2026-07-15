"""Relay受信・永続Outbox送信のバックグラウンドワーカー。"""

import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from enishi_core.config import get_settings
from enishi_core.database import get_session
from enishi_core.models.base import utc_now
from enishi_core.services.approvals import list_approvals
from enishi_core.services.relay_client import RelayTransport, get_relay_client
from enishi_core.services.remote_negotiation import flush_outbox, process_inbox

_status: dict[str, Any] = {
    "configured": False,
    "running": False,
    "last_success": None,
    "last_error": None,
    "processed_total": 0,
}


def status() -> dict[str, Any]:
    value = dict(_status)
    if isinstance(value["last_success"], datetime):
        value["last_success"] = value["last_success"].isoformat()
    return value


def sync_session(session: Session, relay: RelayTransport) -> dict[str, Any]:
    inbox = process_inbox(session, relay)
    # 期限切れ承認を自動解決し、リモート応答をOutboxへ積む。
    list_approvals(session)
    outbox = flush_outbox(session, relay)
    processed = int(inbox["processed"])
    _status["last_success"] = utc_now()
    _status["last_error"] = None
    _status["processed_total"] = int(_status["processed_total"]) + processed
    return {**inbox, "outbox": outbox}


async def _wait_or_stop(stop_event: asyncio.Event, seconds: float) -> bool:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=max(0.01, seconds))
        return True
    except TimeoutError:
        return False


async def worker_loop(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    _status.update(
        configured=bool(settings.relay_url and settings.relay_token),
        running=True,
        last_success=None,
        last_error=None,
        processed_total=0,
    )
    try:
        if not settings.relay_url or not settings.relay_token:
            await stop_event.wait()
            return

        backoff = max(0.01, settings.relay_poll_interval_seconds)
        while not stop_event.is_set():
            session = next(get_session())
            relay = None
            try:
                relay = get_relay_client()
                await asyncio.to_thread(sync_session, session, relay)
                backoff = max(0.01, settings.relay_poll_interval_seconds)
            except Exception as exc:
                session.rollback()
                _status["last_error"] = str(exc)[:500]
                backoff = min(
                    max(backoff * 2, settings.relay_poll_interval_seconds),
                    settings.relay_poll_backoff_max_seconds,
                )
            finally:
                session.close()
                close = getattr(relay, "close", None)
                if callable(close):
                    await asyncio.to_thread(close)
            if await _wait_or_stop(stop_event, backoff):
                break
    finally:
        _status["running"] = False
