"""記憶ソース調査（enishi.md §15）。

選択済みプロジェクトの優先ファイルとGit情報を読み取り専用で収集する。
再帰走査・git書き込み系コマンドは行わない。作者情報は収集しない。
"""

import subprocess
from pathlib import Path
from typing import Any

_PRIORITY_FILES = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "requirements.txt",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
)

_MAX_FILE_BYTES = 64 * 1024

_LANGUAGE_BY_FILE = {
    "pyproject.toml": ["Python"],
    "package.json": ["TypeScript", "JavaScript"],
    "Cargo.toml": ["Rust"],
    "requirements.txt": ["Python"],
}

_KNOWN_FRAMEWORKS = (
    "fastapi",
    "react",
    "tauri",
    "django",
    "flask",
    "next",
    "vue",
    "svelte",
    "express",
    "pydantic",
    "sqlalchemy",
)


def _read_limited(path: Path) -> str:
    """先頭64KBまでをテキストとして読む。"""
    with path.open("rb") as f:
        data = f.read(_MAX_FILE_BYTES)
    return data.decode("utf-8", errors="replace")


def collect_project_signals(root_path: Path) -> dict[str, Any]:
    """プロジェクトルート直下の優先ファイルだけを解析する（LLM不使用）。

    シンボリックリンク等でルート外へ出るパスは読まずにスキップする（§24）。
    """
    root = root_path.resolve()
    languages: list[str] = []
    frameworks: list[str] = []
    readme_summary = ""
    detected_files: list[str] = []

    for name in _PRIORITY_FILES:
        candidate = root / name
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            # ルート外へのシンボリックリンクは読まない
            continue

        detected_files.append(name)
        for language in _LANGUAGE_BY_FILE.get(name, []):
            if language not in languages:
                languages.append(language)

        if name == "README.md":
            readme_summary = _read_limited(resolved)[:500]
        elif name in ("package.json", "pyproject.toml"):
            text = _read_limited(resolved).lower()
            for framework in _KNOWN_FRAMEWORKS:
                if framework in text and framework not in frameworks:
                    frameworks.append(framework)

    return {
        "languages": languages,
        "frameworks": frameworks,
        "readme_summary": readme_summary,
        "detected_files": detected_files,
    }


def _run_git(root: Path, *args: str) -> str | None:
    """引数配列でgit読み取りコマンドを実行する。失敗時はNone。"""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=root,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def collect_git_signals(root_path: Path) -> dict[str, Any] | None:
    """Git情報を読み取り専用で収集する。git書き込み系コマンドは実行しない（§15）。"""
    root = root_path.resolve()
    if not (root / ".git").exists():
        return None

    branch = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    log = _run_git(root, "log", "-5", "--format=%s")
    status = _run_git(root, "status", "--porcelain")
    if branch is None or log is None or status is None:
        return None

    return {
        "current_branch": branch.strip(),
        "recent_commits": [line for line in log.strip().splitlines() if line],
        "changed_files": len([line for line in status.splitlines() if line.strip()]),
    }
