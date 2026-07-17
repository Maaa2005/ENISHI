"""ローカルAPI認証（enishi.md §10）。

Tauriが生成したワンタイムトークンとの一致を検証する。
トークン未設定時はすべて拒否する（127.0.0.1限定でも認証必須）。
"""

import re
import secrets

from fastapi import Header
from starlette.requests import HTTPConnection

from enishi_core.config import get_settings
from enishi_core.errors import EnishiError
from enishi_core.services.core_discovery import mcp_token

_MCP_READ_PATH = re.compile(
    r"^/v1/(?:peers|negotiations(?:/[^/]+(?:/messages)?)?|agent/(?:card|self))$"
)
_MCP_WRITE_PATHS = {
    "/v1/agent/bootstrap",
    "/v1/agent/requests",
    "/v1/peers/from-card",
}


def require_local_token(
    request: HTTPConnection,
    authorization: str | None = Header(default=None),
) -> None:
    expected = get_settings().local_token
    provided = ""
    if authorization is not None and authorization.startswith("Bearer "):
        provided = authorization.removeprefix("Bearer ")

    if expected and secrets.compare_digest(provided, expected):
        return

    scoped = mcp_token()
    if scoped and secrets.compare_digest(provided, scoped):
        method = str(request.scope.get("method", ""))
        allowed = (
            method == "GET" and _MCP_READ_PATH.fullmatch(request.url.path)
        ) or (method == "POST" and request.url.path in _MCP_WRITE_PATHS)
        if allowed:
            return
        raise EnishiError(
            code="MCP_SCOPE_FORBIDDEN",
            message="MCPにはこの操作の権限がありません。",
            status_code=403,
            details={"method": method, "path": request.url.path},
        )

    raise EnishiError(
        code="LOCAL_CORE_UNAUTHORIZED",
        message="ローカル認証トークンが不正です。",
        status_code=401,
    )
