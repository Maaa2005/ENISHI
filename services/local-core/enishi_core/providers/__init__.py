"""外部コーディングエージェントアダプター取得。"""

from enishi_core.errors import EnishiError
from enishi_core.providers.base import CodingAgentAdapter
from enishi_core.providers.claude_code import ClaudeCodeAdapter
from enishi_core.providers.codex import CodexCliAdapter
from enishi_core.providers.mock import MockCodingAgentAdapter


def get_adapter(provider: str) -> CodingAgentAdapter:
    if provider == "codex":
        return CodexCliAdapter()
    if provider == "claude_code":
        return ClaudeCodeAdapter()
    if provider == "mock":
        return MockCodingAgentAdapter()
    raise EnishiError(
        code="PROVIDER_NOT_INSTALLED",
        message="プロバイダが利用できません。",
        status_code=404,
        details={"provider": provider},
    )


__all__ = ["get_adapter"]
