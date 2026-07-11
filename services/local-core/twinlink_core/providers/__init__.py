"""外部コーディングエージェントアダプター取得。"""

from twinlink_core.errors import TwinLinkError
from twinlink_core.providers.base import CodingAgentAdapter
from twinlink_core.providers.claude_code import ClaudeCodeAdapter
from twinlink_core.providers.codex import CodexCliAdapter
from twinlink_core.providers.mock import MockCodingAgentAdapter


def get_adapter(provider: str) -> CodingAgentAdapter:
    if provider == "codex":
        return CodexCliAdapter()
    if provider == "claude_code":
        return ClaudeCodeAdapter()
    if provider == "mock":
        return MockCodingAgentAdapter()
    raise TwinLinkError(
        code="PROVIDER_NOT_INSTALLED",
        message="プロバイダが利用できません。",
        status_code=404,
        details={"provider": provider},
    )


__all__ = ["get_adapter"]
