"""テスト用の決定的なコーディングエージェントアダプター。"""

from pathlib import Path

from enishi_core.models import CloneContextPackage
from enishi_core.providers.base import (
    AuthenticationStatus,
    CodingTaskResult,
    ProviderCapabilities,
    ProviderDetectionResult,
)


class MockCodingAgentAdapter:
    provider = "mock"

    async def detect(self) -> ProviderDetectionResult:
        return ProviderDetectionResult(
            provider=self.provider,
            installed=True,
            path="mock",
            version="mock-1.0",
        )

    async def get_version(self) -> str | None:
        return "mock-1.0"

    async def check_authentication(self) -> AuthenticationStatus:
        return AuthenticationStatus(
            provider=self.provider,
            authenticated=True,
            detail="mock adapter is always authenticated",
        )

    async def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider=self.provider, can_execute=True, help_available=True)

    async def run_task(
        self,
        task_description: str,
        context_package: CloneContextPackage,
        project_root: Path,
    ) -> CodingTaskResult:
        lines = [
            f"task: {task_description}",
            f"coding_rules: {len(context_package.coding_rules)}",
            f"project_root: {project_root}",
            "done",
        ]
        return CodingTaskResult(status="completed", output_lines=lines, detail="mock completed")

    async def cancel_task(self, task_id: str) -> None:
        return None
