"""Local CoreとMCP sidecar間のローカルディスカバリ情報。"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from enishi_core.config import Settings

_mcp_token = ""


def core_info_path(settings: Settings) -> Path:
    return settings.data_dir / "core.json"


def mcp_token() -> str:
    return _mcp_token


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        # sandbox内から他プロセスの確認が拒否された場合は、生存側へ倒す。
        return True
    except OSError:
        return False
    return True


def publish(settings: Settings) -> Path:
    """MCP専用tokenを生成し、0600のcore.jsonをatomicに公開する。"""
    global _mcp_token
    path = core_info_path(settings)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            existing_pid = int(existing.get("pid", 0))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            existing_pid = 0
        if existing_pid != os.getpid() and _process_alive(existing_pid):
            raise RuntimeError("同じデータ領域のENISHI Local Coreが既に起動しています。")
    _mcp_token = secrets.token_urlsafe(32)
    temporary = path.with_suffix(".json.tmp")
    payload = {
        "port": settings.local_port,
        "token": _mcp_token,
        "owner": os.environ.get("ENISHI_CORE_OWNER", "standalone"),
        "pid": os.getpid(),
    }
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)
    return path


def unpublish(settings: Settings) -> None:
    global _mcp_token
    path = core_info_path(settings)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if payload.get("pid") == os.getpid() and payload.get("token") == _mcp_token:
            path.unlink(missing_ok=True)
    _mcp_token = ""
