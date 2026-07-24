"""Obsidian Vault / Markdownフォルダをローカル記憶へ同期する。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from enishi_core.errors import EnishiError
from enishi_core.models import MemoryItem, MemoryStatus
from enishi_core.models.base import new_id, utc_now

MAX_FILES = 1_000
MAX_FILE_BYTES = 256 * 1024
_CATEGORY_BY_TYPE = {
    "decision": "Decisions",
    "preference": "Preferences",
    "negative_preference": "Preferences",
    "project": "Projects",
    "project_state": "Projects",
}


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


def _slug(value: str) -> str:
    normalized = re.sub(r"[^\w-]+", "-", value, flags=re.UNICODE).strip("-_")
    return (normalized or "memory")[:80]


def _managed_relative_path(memory_type: str, title: str, memory_id: str) -> Path:
    category = _CATEGORY_BY_TYPE.get(memory_type, "Knowledge")
    date_prefix = (
        f"{datetime.now(UTC).date().isoformat()}-" if memory_type == "decision" else ""
    )
    return Path(category) / f"{date_prefix}{_slug(title)}-{memory_id[:8]}.md"


def _markdown_body(
    *,
    memory_id: str,
    memory_type: str,
    title: str,
    text: str,
    sensitivity: str,
    tags: list[str],
) -> str:
    frontmatter = [
        "---",
        f"date: {datetime.now(UTC).date().isoformat()}",
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        'project: ""',
        "related: []",
        f"enishi_id: {json.dumps(memory_id)}",
        f"memory_type: {json.dumps(memory_type)}",
        f"sensitivity: {json.dumps(sensitivity)}",
        "---",
    ]
    return "\n".join(frontmatter) + f"\n\n# {title}\n\n{text.rstrip()}\n\n(enishi)\n"


def _atomic_write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(body)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _target_within_root(root: Path, relative: Path) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise EnishiError(
            code="MEMORY_SOURCE_PATH_INVALID",
            message="外部脳の管理範囲外へは書き込めません。",
            status_code=400,
        )
    return target


def write_markdown_memory(
    session: Session,
    *,
    user_id: str,
    source: str,
    raw_path: str,
    title: str,
    text: str,
    memory_type: str,
    sensitivity: str,
    tags: list[str],
    memory_id: str | None = None,
) -> MemoryItem:
    """ENISHI管理ノートへ原子的に書き、DBには再生成可能な索引を作る。"""
    root = validate_markdown_root(raw_path)
    if not os.access(root, os.W_OK):
        raise EnishiError(
            code="MEMORY_SOURCE_READ_ONLY",
            message="外部脳へ書き込めません。",
            status_code=409,
            details={"path": str(root)},
        )
    canonical_id = memory_id or new_id()
    matches = list(
        session.scalars(
            select(MemoryItem).where(
                MemoryItem.user_id == user_id,
                MemoryItem.source_type == source,
                MemoryItem.memory_type == memory_type,
                MemoryItem.title == title,
                MemoryItem.status == MemoryStatus.ACTIVE.value,
            )
        )
    )
    existing = next(
        (item for item in matches if item.content.get("managed_by") == "enishi"),
        None,
    )
    if existing is not None:
        canonical_id = str(existing.content.get("enishi_id") or existing.id)
        relative = Path(str(existing.content["relative_path"]))
    else:
        relative = _managed_relative_path(memory_type, title, canonical_id)
    body = _markdown_body(
        memory_id=canonical_id,
        memory_type=memory_type,
        title=title,
        text=text,
        sensitivity=sensitivity,
        tags=tags,
    )
    path = _target_within_root(root, relative)
    _atomic_write(path, body)
    digest = hashlib.sha256(body.encode()).hexdigest()
    reference = f"{source}:{root}:{relative.as_posix()}"
    content: dict[str, Any] = {
        "text": text,
        "relative_path": relative.as_posix(),
        "root": str(root),
        "sha256": digest,
        "managed_by": "enishi",
        "enishi_id": canonical_id,
    }
    searchable_text = f"{title}\n{text}"[:2000]
    if existing is None:
        existing = MemoryItem(
            id=canonical_id,
            user_id=user_id,
            source_type=source,
            source_reference=reference,
            memory_type=memory_type,
            title=title,
            content=content,
            searchable_text=searchable_text,
            confidence=1.0,
            sensitivity=sensitivity,
            relevance_tags=tags,
        )
        session.add(existing)
    else:
        existing.source_reference = reference
        existing.content = content
        existing.searchable_text = searchable_text
        existing.sensitivity = sensitivity
        existing.relevance_tags = tags
        existing.updated_at = utc_now()
    session.commit()
    session.refresh(existing)
    return existing


def sync_markdown_folder(
    session: Session, *, user_id: str, source: str, raw_path: str
) -> dict[str, int | str]:
    root = validate_markdown_root(raw_path)
    created = updated = unchanged = skipped = deleted = 0
    files = sorted(root.rglob("*.md"))[:MAX_FILES]
    seen_references: set[str] = set()
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
        seen_references.add(reference)
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
        if memory is not None and memory.content.get("managed_by") == "enishi":
            content["managed_by"] = "enishi"
            content["enishi_id"] = memory.content.get("enishi_id", memory.id)
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
    if len(files) < MAX_FILES:
        prefix = f"{source}:{root}:"
        imported = session.scalars(
            select(MemoryItem).where(
                MemoryItem.user_id == user_id,
                MemoryItem.source_type == source,
                MemoryItem.source_reference.like(f"{prefix}%"),
                MemoryItem.status == MemoryStatus.ACTIVE.value,
            )
        )
        for memory in imported:
            if memory.source_reference not in seen_references:
                memory.status = MemoryStatus.DELETED.value
                memory.updated_at = utc_now()
                deleted += 1
    session.commit()
    return {
        "source": source,
        "root": str(root),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "skipped": skipped,
        "deleted": deleted,
    }
