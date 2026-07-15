"""Claude Code CLIアダプター（enishi.md §22）。"""

from pathlib import Path

from enishi_core.models import CloneContextPackage
from enishi_core.providers.base import (
    AuthenticationStatus,
    CodingTaskResult,
    ProviderCapabilities,
    ProviderDetectionResult,
)
from enishi_core.providers.cli_runner import run_cli, run_cli_async
from enishi_core.services.environment import detect_provider


def build_task_command(
    task_description: str,
    context_json_path: Path,
    project_root: Path,
) -> list[str]:
    """Claude Code実行コマンドを引数配列で構築する。"""
    prompt = (
        f"Task:\n{task_description}\n\n"
        f"Context package JSON: {context_json_path}\n"
        "Follow the package rules and do not read credential files."
    )
    return ["claude", "-p", prompt, "--add-dir", str(project_root)]


class ClaudeCodeAdapter:
    provider = "claude_code"

    async def detect(self) -> ProviderDetectionResult:
        status = detect_provider(self.provider)
        return ProviderDetectionResult(**status.model_dump())

    async def get_version(self) -> str | None:
        detected = await self.detect()
        return detected.version

    async def check_authentication(self) -> AuthenticationStatus:
        help_code, help_output = run_cli(["claude", "--help"], timeout=10)
        if help_code != 0:
            return AuthenticationStatus(
                provider=self.provider,
                authenticated=None,
                detail="authentication status is unknown",
            )
        return AuthenticationStatus(
            provider=self.provider,
            authenticated="login" in help_output or "auth" in help_output.lower(),
            detail="help command completed",
        )

    async def get_capabilities(self) -> ProviderCapabilities:
        help_code, _help_output = run_cli(["claude", "--help"], timeout=10)
        return ProviderCapabilities(
            provider=self.provider,
            can_execute=help_code == 0,
            help_available=help_code == 0,
        )

    async def run_task(
        self,
        task_description: str,
        context_package: CloneContextPackage,
        project_root: Path,
    ) -> CodingTaskResult:
        context_path = project_root / f".enishi-context-{context_package.id}.json"
        args = build_task_command(task_description, context_path, project_root)
        return_code, output = await run_cli_async(args, cwd=project_root, timeout=600)
        lines = [line for line in output.splitlines() if line]
        status = "completed" if return_code == 0 else "failed"
        return CodingTaskResult(status=status, output_lines=lines, detail=f"exit={return_code}")

    async def cancel_task(self, task_id: str) -> None:
        return None
