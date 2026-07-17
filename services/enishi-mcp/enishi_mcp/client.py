"""core.jsonを介してLocal Coreへ接続するHTTPクライアント。"""

from __future__ import annotations

import json
import os
import secrets
import socket
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx


class CoreUnavailable(RuntimeError):
    pass


_AUTOSTART_TIMEOUT_SECONDS = 20.0


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


def _autostart_enabled() -> bool:
    return os.environ.get("ENISHI_CORE_AUTOSTART", "1").lower() not in {
        "0",
        "false",
        "no",
    }


def _pick_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _core_listening(info: dict[str, Any]) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=0.2):
            return True
    except OSError:
        return False


def _core_command(port: int) -> list[str]:
    binary = os.environ.get("ENISHI_CORE_BINARY")
    if binary and Path(binary).expanduser().is_file():
        return [str(Path(binary).expanduser()), "--port", str(port)]
    return [sys.executable, "-m", "enishi_core.sidecar", "--port", str(port)]


@contextmanager
def _startup_lock(path: Path) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        if os.name == "posix":
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "posix":
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def start_local_core(path: Path | None = None) -> dict[str, Any]:
    """ENISHI UIなしでLocal Coreを起動し、MCP接続情報を返す。"""
    target = path or default_core_info_path()
    with _startup_lock(target.with_name("core-start.lock")):
        try:
            existing = load_core_info(target)
        except CoreUnavailable:
            existing = None
        if existing is not None:
            existing_deadline = time.monotonic() + 3.0
            while time.monotonic() < existing_deadline:
                if _core_listening(existing):
                    return existing
                time.sleep(0.1)
            raise CoreUnavailable("既存のENISHI Local Coreが応答していません。")

        port = _pick_loopback_port()
        target.parent.mkdir(parents=True, exist_ok=True)
        log_dir = Path(
            os.environ.get(
                "ENISHI_LOG_DIR",
                str(Path.home() / "Library" / "Logs" / "ENISHI"),
            )
        ).expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(
            {
                "ENISHI_LOCAL_PORT": str(port),
                "ENISHI_LOCAL_TOKEN": secrets.token_urlsafe(36),
                "ENISHI_DATA_DIR": str(target.parent),
                "ENISHI_KEYRING_SERVICE": "com.enishi.desktop",
                "ENISHI_CORE_OWNER": "headless",
            }
        )
        log_path = log_dir / "headless-core.log"
        with log_path.open("ab") as log:
            try:
                subprocess.Popen(
                    _core_command(port),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as exc:
                raise CoreUnavailable(
                    "ENISHI Local Coreをバックグラウンド起動できませんでした。"
                ) from exc

        deadline = time.monotonic() + _AUTOSTART_TIMEOUT_SECONDS
        last_error: CoreUnavailable | None = None
        while time.monotonic() < deadline:
            try:
                info = load_core_info(target)
                if _core_listening(info):
                    return info
            except CoreUnavailable as exc:
                last_error = exc
            time.sleep(0.1)
        raise CoreUnavailable(
            f"ENISHI Local Coreの起動が完了しませんでした。ログ: {log_path}"
        ) from last_error


class CoreClient:
    def __init__(
        self,
        *,
        info_path: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        autostart: bool | None = None,
    ) -> None:
        self.info_path = info_path
        self.transport = transport
        self.autostart = _autostart_enabled() if autostart is None else autostart

    def _info(self) -> dict[str, Any]:
        try:
            return load_core_info(self.info_path)
        except CoreUnavailable:
            if not self.autostart:
                raise
            return start_local_core(self.info_path)

    async def request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        info = self._info()
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
