"""Relay Serverクライアント（twinlink.md §25 Relay Serverの責務 v2）。

サービス層はRelayTransport（Protocol）を受け取り、テストではFakeへ差し替える。
"""

from typing import Any, Protocol

import httpx

from twinlink_core.config import get_settings
from twinlink_core.errors import TwinLinkError


class RelayTransport(Protocol):
    """Relayとの送受信インターフェース。"""

    def send(self, envelope: dict[str, Any]) -> None: ...

    def fetch(self) -> list[dict[str, Any]]: ...

    def ack(self, delivery_id: str) -> None: ...


def _unavailable(exc: Exception) -> TwinLinkError:
    return TwinLinkError(
        code="RELAY_UNAVAILABLE",
        message="Relay Serverへ接続できません。",
        status_code=503,
        details={"reason": str(exc)},
    )


class RelayClient:
    """httpxによる実Relayクライアント。"""

    def __init__(self, base_url: str, token: str) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )

    def send(self, envelope: dict[str, Any]) -> None:
        try:
            response = self._client.post("/v1/messages", json=envelope)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise _unavailable(exc) from exc

    def fetch(self) -> list[dict[str, Any]]:
        try:
            response = self._client.get("/v1/messages")
            response.raise_for_status()
            return list(response.json())
        except httpx.HTTPError as exc:
            raise _unavailable(exc) from exc

    def ack(self, delivery_id: str) -> None:
        try:
            response = self._client.post(f"/v1/messages/{delivery_id}/ack")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise _unavailable(exc) from exc

    def close(self) -> None:
        self._client.close()


def get_relay_client() -> RelayClient:
    """設定からRelayクライアントを生成する。未設定はRELAY_UNAVAILABLE。"""
    settings = get_settings()
    if not settings.relay_url or not settings.relay_token:
        raise TwinLinkError(
            code="RELAY_UNAVAILABLE",
            message="Relayの接続設定（TWINLINK_RELAY_URL / TWINLINK_RELAY_TOKEN）がありません。",
            status_code=503,
        )
    return RelayClient(settings.relay_url, settings.relay_token)
