"""意思決定ドメインのレジストリ。

`register(domain)` で登録し、`get_domain(intent)` で intent から解決する。
新しいドメインの追加手順は `domains/README.md` を参照。
"""

from enishi_core.domains.base import DecisionDomain
from enishi_core.domains.cost_split import CostSplitDomain
from enishi_core.domains.meeting_schedule import MeetingScheduleDomain
from enishi_core.domains.task_request import TaskRequestDomain
from enishi_core.errors import EnishiError

_REGISTRY: dict[str, DecisionDomain] = {}


def register(domain: DecisionDomain) -> None:
    _REGISTRY[domain.intent] = domain


def registered_intents() -> list[str]:
    return sorted(_REGISTRY)


def get_domain(intent: str) -> DecisionDomain:
    domain = _REGISTRY.get(intent)
    if domain is None:
        raise EnishiError(
            code="UNKNOWN_INTENT",
            message=f"未登録の intent です: {intent}",
            status_code=422,
            details={"registered_intents": registered_intents()},
        )
    return domain


register(MeetingScheduleDomain())
register(TaskRequestDomain())
register(CostSplitDomain())
