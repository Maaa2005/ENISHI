"""Codex / Claude Code向けstdio MCPサーバー。ENISHI UIは不要。"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy.orm import Session

from enishi_core.config import get_settings
from enishi_core.database import get_session, init_database
from enishi_core.services import second_brain

mcp = FastMCP(
    "ENISHI Second Brain",
    instructions=(
        "作業前に関連記憶を検索する。保存はユーザーが確定した判断・嗜好・知見だけにし、"
        "推測や秘密情報は保存しない。外部メモリが未接続でもENISHI内蔵メモリを使える。"
    ),
)


@contextmanager
def _session() -> Any:
    iterator = get_session()
    session = next(iterator)
    try:
        yield session
    finally:
        session.close()


def _user_id(session: Session) -> str:
    return second_brain.ensure_local_user(session, os.getenv("ENISHI_USER_ID")).id


def _read(memory: Any) -> dict[str, Any]:
    return {
        "id": memory.id,
        "type": memory.memory_type,
        "title": memory.title,
        "content": memory.content,
        "source": memory.source_type,
        "sensitivity": memory.sensitivity,
        "tags": memory.relevance_tags,
        "updated_at": memory.updated_at.isoformat(),
    }


@mcp.tool()
def search_memories(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """ENISHIと接続済み外部メモリから、現在の作業に関係する記憶を検索する。"""
    with _session() as session:
        return [_read(item) for item in second_brain.search(
            session, user_id=_user_id(session), query=query, limit=limit
        )]


@mcp.tool()
def remember(
    title: str,
    text: str,
    memory_type: str = "episodic",
    sensitivity: str = "private",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """ユーザーが確定した長期的な知見・嗜好・判断をENISHIへ保存する。秘密は保存しない。"""
    if sensitivity == "secret":
        raise ValueError("MCP経由ではsecretを保存できません")
    with _session() as session:
        return _read(second_brain.remember(
            session,
            user_id=_user_id(session),
            title=title,
            text=text,
            memory_type=memory_type,
            sensitivity=sensitivity,
            tags=tags,
        ))


@mcp.tool()
def record_decision(
    title: str, decision: str, rationale: str = "", project: str = ""
) -> dict[str, Any]:
    """ユーザーが確定した判断と理由を、decision記憶として保存する。"""
    text = decision + (f"\n理由: {rationale}" if rationale else "")
    tags = ["decision"] + ([project] if project else [])
    with _session() as session:
        return _read(second_brain.remember(
            session, user_id=_user_id(session), title=title, text=text,
            memory_type="decision", sensitivity="private", tags=tags
        ))


def main() -> None:
    settings = get_settings()
    settings.ensure_directories()
    init_database()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
