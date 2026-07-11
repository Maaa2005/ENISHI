"""ローカルAPI認証（twinlink.md §10）。

Tauriが生成したワンタイムトークンとの一致を検証する。
トークン未設定時はすべて拒否する（127.0.0.1限定でも認証必須）。
"""

import secrets

from fastapi import Header

from twinlink_core.config import get_settings
from twinlink_core.errors import TwinLinkError


def require_local_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().local_token
    provided = ""
    if authorization is not None and authorization.startswith("Bearer "):
        provided = authorization.removeprefix("Bearer ")

    if not expected or not secrets.compare_digest(provided, expected):
        raise TwinLinkError(
            code="LOCAL_CORE_UNAUTHORIZED",
            message="ローカル認証トークンが不正です。",
            status_code=401,
        )
