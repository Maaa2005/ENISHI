"""macOS環境とコーディングエージェントCLIの検出。

CLIはコマンド名と引数を配列で分離して実行する（シェル文字列を組み立てない）。
"""

import platform
import shutil
import subprocess

from twinlink_core.schemas import EnvironmentInfo, ProviderStatus

_PROVIDER_COMMANDS = {
    "codex": "codex",
    "claude_code": "claude",
}


def detect_provider(provider: str) -> ProviderStatus:
    command = _PROVIDER_COMMANDS.get(provider)
    if command is None:
        return ProviderStatus(provider=provider, installed=False)

    path = shutil.which(command)
    if path is None:
        return ProviderStatus(provider=provider, installed=False)

    version: str | None = None
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
    except (subprocess.TimeoutExpired, OSError):
        version = None

    return ProviderStatus(provider=provider, installed=True, path=path, version=version)


def get_environment() -> EnvironmentInfo:
    machine = platform.machine()
    return EnvironmentInfo(
        macos_version=platform.mac_ver()[0] or "unknown",
        architecture=machine,
        is_apple_silicon=machine == "arm64",
        python_version=platform.python_version(),
        providers=[detect_provider(p) for p in _PROVIDER_COMMANDS],
    )
