"""交渉候補に対する本人エージェント判断。副作用を持たない。

共通ガード層（全ドメイン共通・人間の権限の中核）と、ドメイン固有の評価層を分離する。
ドメイン固有の評価（会議の時間帯の好み等）は `enishi_core.domains` 配下にある。
"""

from dataclasses import dataclass
from typing import Any, Literal

from enishi_core.domains.meeting_schedule import evaluate_meeting_preferences
from enishi_core.models import CloneAgent

DecisionOutcome = Literal["auto_accept", "approval_required", "counter", "reject"]
CONFIDENCE_THRESHOLD = 0.6


@dataclass(frozen=True)
class DecisionEvaluation:
    outcome: DecisionOutcome
    reason_codes: list[str]
    evidence: dict[str, Any]
    confidence: float
    policy_version: int


@dataclass(frozen=True)
class CommonGuardResult:
    """全ドメイン共通のガード判定結果。

    delegation/confidence は判断の先頭に、relationship は末尾に来る（既存の並び順）ため、
    reason_codes を pre/post に分けて呼び出し側でドメイン固有の理由を挟み込めるようにする。
    """

    confidence: float
    pre_reason_codes: list[str]
    post_reason_codes: list[str]
    evidence: dict[str, Any]


def evaluate_common_guards(
    *,
    clone: CloneAgent,
    delegation_enabled: bool,
    peer_personal_agent_id: str,
    not_delegated_reason_code: str,
) -> CommonGuardResult:
    """委任・confidence・関係性という、全ドメイン共通のガードを評価する。"""
    confidence = max(0.0, min(1.0, float(clone.confidence_score)))

    pre_reason_codes: list[str] = []
    if not delegation_enabled:
        pre_reason_codes.append(not_delegated_reason_code)
    if confidence < CONFIDENCE_THRESHOLD:
        pre_reason_codes.append("clone_confidence_below_threshold")

    relationship_auto_accept: bool | None = None
    relationships = clone.preference_profile.get("relationships", {})
    if isinstance(relationships, dict):
        relationship = relationships.get(peer_personal_agent_id, {})
        if isinstance(relationship, dict) and isinstance(
            relationship.get("allow_auto_accept"), bool
        ):
            relationship_auto_accept = relationship["allow_auto_accept"]

    post_reason_codes: list[str] = []
    if relationship_auto_accept is False:
        post_reason_codes.append("relationship_requires_approval")

    return CommonGuardResult(
        confidence=confidence,
        pre_reason_codes=pre_reason_codes,
        post_reason_codes=post_reason_codes,
        evidence={
            "delegation_enabled": delegation_enabled,
            "clone_confidence": confidence,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "relationship_auto_accept": relationship_auto_accept,
        },
    )


def evaluate_meeting_schedule(
    *,
    clone: CloneAgent,
    delegation_enabled: bool,
    common_slot_count: int,
    selected_slot: dict[str, Any] | None,
    peer_personal_agent_id: str,
    timezone: str = "UTC",
) -> DecisionEvaluation:
    """公開可能な集約値だけを根拠に、決定的な順序で判断する。

    薄いラッパ。共通ガードは `evaluate_common_guards`、会議固有の評価は
    `enishi_core.domains.meeting_schedule.evaluate_meeting_preferences` が担う。
    """
    guards = evaluate_common_guards(
        clone=clone,
        delegation_enabled=delegation_enabled,
        peer_personal_agent_id=peer_personal_agent_id,
        not_delegated_reason_code="schedule_negotiation_not_delegated",
    )
    domain_result = evaluate_meeting_preferences(
        clone=clone,
        selected_slot=selected_slot,
        timezone=timezone,
    )

    # 現行の追加順: not_delegated -> confidence -> auto_accept_disabled ->
    # outside_preferred_time -> time_avoided -> relationship_requires_approval
    reason_codes = [
        *guards.pre_reason_codes,
        *domain_result.reason_codes,
        *guards.post_reason_codes,
    ]

    if reason_codes:
        outcome: DecisionOutcome = "approval_required"
    elif common_slot_count > 0:
        outcome = "auto_accept"
        reason_codes = ["common_slot_within_delegation"]
    else:
        outcome = "counter"
        reason_codes = ["no_common_slot"]

    evidence = {
        **guards.evidence,
        **domain_result.evidence,
        "common_slot_count": common_slot_count,
    }

    return DecisionEvaluation(
        outcome=outcome,
        reason_codes=reason_codes,
        evidence=evidence,
        confidence=guards.confidence,
        policy_version=clone.version,
    )
