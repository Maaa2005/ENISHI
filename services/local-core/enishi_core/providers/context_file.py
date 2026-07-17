"""CLI providerへ渡す一時コンテキストファイル。"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from enishi_core.models import CloneContextPackage


@contextmanager
def materialize_context(package: CloneContextPackage, project_root: Path) -> Iterator[Path]:
    path = project_root / f".enishi-context-{package.id}.json"
    fields = (
        "id", "clone_id", "clone_version", "task_id", "project_id", "task_goal",
        "relevant_preferences", "relevant_skills", "relevant_project_context",
        "relevant_decisions", "coding_rules", "prohibited_actions",
        "approval_requirements", "file_references", "estimated_tokens", "content_hash",
    )
    payload = {key: getattr(package, key) for key in fields}
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    path.chmod(0o600)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
