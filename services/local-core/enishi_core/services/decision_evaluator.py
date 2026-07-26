"""交渉候補に対する本人エージェント判断。副作用を持たない。

共通ガード層（全ドメイン共通・人間の権限の中核）と、ドメイン固有の評価層を分離する。
ドメイン固有の評価（会議の時間帯の好み等）は `enishi_core.domains` 配下にある。

E3-a: `evaluate_common_guards` / `DecisionEvaluation` / `CommonGuardResult` /
`CONFIDENCE_THRESHOLD` の実体は `enishi_core.domains.common` にある（ドメイン側の
評価関数からも参照できるよう、循環 import を避けて移した）。ここでは後方互換のため
再エクスポートする。`evaluate_meeting_schedule` も実体は
`enishi_core.domains.meeting_schedule.evaluate_meeting_schedule` へ委譲する薄いラッパで、
`tests/test_agent_decisions.py` が直接 import しているため残す。
"""

from typing import Any

from enishi_core.domains.common import (
    CONFIDENCE_THRESHOLD as CONFIDENCE_THRESHOLD,
)
from enishi_core.domains.common import (
    CommonGuardResult as CommonGuardResult,
)
from enishi_core.domains.common import (
    DecisionEvaluation as DecisionEvaluation,
)
from enishi_core.domains.common import (
    evaluate_common_guards as evaluate_common_guards,
)
from enishi_core.domains.meeting_schedule import (
    evaluate_meeting_schedule as _evaluate_meeting_schedule,
)


def evaluate_meeting_schedule(
    *,
    clone: Any,
    delegation_enabled: bool,
    common_slot_count: int,
    selected_slot: dict[str, Any] | None,
    peer_personal_agent_id: str,
    timezone: str = "UTC",
) -> DecisionEvaluation:
    """後方互換ラッパ。実体は `domains.meeting_schedule.evaluate_meeting_schedule`（E3-a）。"""
    return _evaluate_meeting_schedule(
        clone=clone,
        delegation_enabled=delegation_enabled,
        common_slot_count=common_slot_count,
        selected_slot=selected_slot,
        peer_personal_agent_id=peer_personal_agent_id,
        timezone=timezone,
    )
