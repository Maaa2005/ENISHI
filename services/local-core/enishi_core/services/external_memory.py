"""Obsidian Vault / Markdownフォルダをローカル記憶へ同期する。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from enishi_core.errors import EnishiError
from enishi_core.models import MemoryItem, MemoryStatus
from enishi_core.models.base import utc_now

MAX_FILES = 1_000
MAX_FILE_BYTES = 256 * 1024


def discover_markdown_sources() -> list[dict[str, str]]:
    """既定候補を検出するだけで、読み込みや接続は行わない。"""
    candidates = [Path.home() / "Vault", Path.home() / "Documents" / "Obsidian"]
    return [
        {"source": "obsidian", "path": str(path.resolve()), "label": path.name}
        for path in candidates
        if path.is_dir() and any(path.rglob("*.md"))
    ]


def validate_markdown_root(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not path.is_dir():
        raise EnishiError(
            code="MEMORY_SOURCE_NOT_FOUND",
            message="Markdownフォルダが見つかりません。",
            status_code=400,
            details={"path": str(path)},
        )
    return path


def sync_markdown_folder(
    session: Session, *, user_id: str, source: str, raw_path: str
) -> dict[str, int | str]:
    root = validate_markdown_root(raw_path)
    created = updated = unchanged = skipped = 0
    files = sorted(root.rglob("*.md"))[:MAX_FILES]
    for path in files:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            skipped += 1
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            skipped += 1
            continue
        relative = path.relative_to(root).as_posix()
        reference = f"{source}:{root}:{relative}"
        digest = hashlib.sha256(body.encode()).hexdigest()
        memory = session.scalar(
            select(MemoryItem).where(
                MemoryItem.user_id == user_id,
                MemoryItem.source_type == source,
                MemoryItem.source_reference == reference,
            )
        )
        content = {
            "text": body,
            "relative_path": relative,
            "root": str(root),
            "sha256": digest,
        }
        title = next(
            (line.removeprefix("#").strip() for line in body.splitlines() if line.startswith("#")),
            path.stem,
        )[:200]
        if memory is None:
            session.add(
                MemoryItem(
                    user_id=user_id,
                    source_type=source,
                    source_reference=reference,
                    memory_type="project",
                    title=title,
                    content=content,
                    searchable_text=f"{title}\n{body}"[:2000],
                    confidence=1.0,
                    sensitivity="private",
                    relevance_tags=["external-memory", source],
                )
            )
            created += 1
        elif memory.content.get("sha256") != digest or memory.status != MemoryStatus.ACTIVE.value:
            memory.title = title
            memory.content = content
            memory.searchable_text = f"{title}\n{body}"[:2000]
            memory.status = MemoryStatus.ACTIVE.value
            memory.updated_at = utc_now()
            updated += 1
        else:
            unchanged += 1
    session.commit()
    return {
        "source": source,
        "root": str(root),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "skipped": skipped,
    }
