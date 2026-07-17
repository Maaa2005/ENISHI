"""core.jsonを介してLocal Coreへ接続するHTTPクライアント。"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import httpx


class CoreUnavailable(RuntimeError):
    pass


def default_core_info_path() -> Path:
    override = os.environ.get("ENISHI_CORE_INFO_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Application Support" / "ENISHI" / "core.json"


def load_core_info(path: Path | None = None) -> dict[str, Any]:
    target = path or default_core_info_path()
    if not target.is_file():
        raise CoreUnavailable(
            "ENISHI Local Coreが起動していません。ENISHIを起動してから再実行してください。"
        )
    if os.name == "posix" and stat.S_IMODE(target.stat().st_mode) & 0o077:
        raise CoreUnavailable("core.jsonの権限が安全ではありません。ENISHIを再起動してください。")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        port = int(payload["port"])
        token = str(payload["token"])
        pid = int(payload["pid"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CoreUnavailable("core.jsonが不正です。ENISHIを再起動してください。") from exc
    if not 1 <= port <= 65535 or len(token) < 32 or pid <= 0:
        raise CoreUnavailable("core.jsonが不正です。ENISHIを再起動してください。")
    try:
        os.kill(pid, 0)
    except PermissionError:
        # sandboxによってPID確認だけが拒否されても、loopback HTTP確認は続ける。
        pass
    except OSError as exc:
        raise CoreUnavailable("ENISHI Local Coreのプロセスを確認できません。") from exc
    return {"port": port, "token": token, "pid": pid}


class CoreClient:
    def __init__(
        self,
        *,
        info_path: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.info_path = info_path
        self.transport = transport

    async def request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        info = load_core_info(self.info_path)
        try:
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{info['port']}",
                headers={"Authorization": f"Bearer {info['token']}"},
                transport=self.transport,
                timeout=10,
            ) as client:
                response = await client.request(method, path, params=params, json=json_body)
        except httpx.HTTPError as exc:
            raise CoreUnavailable("ENISHI Local Coreへ接続できません。") from exc
        if response.is_error:
            try:
                error = response.json().get("error", {})
                message = error.get("message") or response.text
            except (ValueError, AttributeError):
                message = response.text
            raise RuntimeError(f"Local Core error ({response.status_code}): {message}")
        return response.json()
