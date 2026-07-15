"""外部コーディングエージェント共通インターフェース。"""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from enishi_core.models import CloneContextPackage


class ProviderDetectionResult(BaseModel):
    provider: str
    installed: bool
    path: str | None = None
    version: str | None = None


class AuthenticationStatus(BaseModel):
    provider: str
    authenticated: bool | None
    detail: str


class ProviderCapabilities(BaseModel):
    provider: str
    can_execute: bool
    help_available: bool


class CodingTaskResult(BaseModel):
    status: str
    output_lines: list[str]
    detail: str


class CodingAgentAdapter(Protocol):
    provider: str

    async def detect(self) -> ProviderDetectionResult:
        """CLIの存在とバージョンを検出する。"""

    async def get_version(self) -> str | None:
        """CLIのバージョンを返す。"""

    async def check_authentication(self) -> AuthenticationStatus:
        """認証状態を返す。"""

    async def get_capabilities(self) -> ProviderCapabilities:
        """実行可能性を返す。"""

    async def run_task(
        self,
        task_description: str,
        context_package: CloneContextPackage,
        project_root: Path,
    ) -> CodingTaskResult:
        """タスクを実行する。"""

    async def cancel_task(self, task_id: str) -> None:
        """実行中タスクをキャンセルする。"""
