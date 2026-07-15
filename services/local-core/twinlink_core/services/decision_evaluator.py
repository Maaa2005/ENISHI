"""交渉候補に対する本人エージェント判断。副作用を持たない。"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Literal

from twinlink_core.models import CloneAgent

DecisionOutcome = Literal["auto_accept", "approval_required", "counter", "reject"]
CONFIDENCE_THRESHOLD = 0.6


@dataclass(frozen=True)
class DecisionEvaluation:
    outcome: DecisionOutcome
    reason_codes: list[str]
    evidence: dict[str, Any]
    confidence: float
    policy_version: int


def evaluate_meeting_schedule(
    *,
    clone: CloneAgent,
    delegation_enabled: bool,
    common_slot_count: int,
    selected_slot: dict[str, Any] | None,
    peer_personal_agent_id: str,
) -> DecisionEvaluation:
    """公開可能な集約値だけを根拠に、決定的な順序で判断する。"""
    confidence = max(0.0, min(1.0, float(clone.confidence_score)))
    raw_meeting_policy = clone.policy_profile.get("meeting_schedule", {})
    meeting_auto_accept: bool | None = None
    if isinstance(raw_meeting_policy, dict) and "auto_accept" in raw_meeting_policy:
        raw_value = raw_meeting_policy["auto_accept"]
        if isinstance(raw_value, bool):
            meeting_auto_accept = raw_value

    reason_codes: list[str] = []
    if not delegation_enabled:
        reason_codes.append("schedule_negotiation_not_delegated")
    if confidence < CONFIDENCE_THRESHOLD:
        reason_codes.append("clone_confidence_below_threshold")
    if meeting_auto_accept is False:
        reason_codes.append("meeting_auto_accept_disabled")

    meeting_preferences = clone.preference_profile.get("meeting_schedule", {})
    preferred_ranges: list[dict[str, str]] = []
    avoid_ranges: list[dict[str, str]] = []
    if isinstance(meeting_preferences, dict):
        preferred_ranges = _valid_time_ranges(
            meeting_preferences.get("preferred_time_ranges")
        )
        avoid_ranges = _valid_time_ranges(meeting_preferences.get("avoid_time_ranges"))
    selected_time = _slot_start_time(selected_slot)
    within_preferred = (
        selected_time is not None
        and (not preferred_ranges or _time_in_ranges(selected_time, preferred_ranges))
    )
    within_avoided = selected_time is not None and _time_in_ranges(
        selected_time, avoid_ranges
    )
    if preferred_ranges and not within_preferred:
        reason_codes.append("meeting_outside_preferred_time")
    if within_avoided:
        reason_codes.append("meeting_time_avoided")

    relationship_auto_accept: bool | None = None
    relationships = clone.preference_profile.get("relationships", {})
    if isinstance(relationships, dict):
        relationship = relationships.get(peer_personal_agent_id, {})
        if isinstance(relationship, dict) and isinstance(
            relationship.get("allow_auto_accept"), bool
        ):
            relationship_auto_accept = relationship["allow_auto_accept"]
    if relationship_auto_accept is False:
        reason_codes.append("relationship_requires_approval")

    if reason_codes:
        outcome: DecisionOutcome = "approval_required"
    elif common_slot_count > 0:
        outcome = "auto_accept"
        reason_codes = ["common_slot_within_delegation"]
    else:
        outcome = "counter"
        reason_codes = ["no_common_slot"]

    return DecisionEvaluation(
        outcome=outcome,
        reason_codes=reason_codes,
        evidence={
            "delegation_enabled": delegation_enabled,
            "clone_confidence": confidence,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "meeting_auto_accept": meeting_auto_accept,
            "common_slot_count": common_slot_count,
            "preferred_time_configured": bool(preferred_ranges),
            "selected_time_within_preference": within_preferred,
            "selected_time_avoided": within_avoided,
            "relationship_auto_accept": relationship_auto_accept,
        },
        confidence=confidence,
        policy_version=clone.version,
    )


def _valid_time_ranges(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    valid: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        start = item.get("start")
        end = item.get("end")
        if not isinstance(start, str) or not isinstance(end, str):
            continue
        try:
            start_time = time.fromisoformat(start)
            end_time = time.fromisoformat(end)
        except ValueError:
            continue
        if start_time >= end_time:
            continue
        valid.append({"start": start, "end": end})
    return valid


def _slot_start_time(selected_slot: dict[str, Any] | None) -> time | None:
    if not selected_slot or not isinstance(selected_slot.get("start"), str):
        return None
    try:
        return datetime.fromisoformat(str(selected_slot["start"])).time()
    except ValueError:
        return None


def _time_in_ranges(value: time, ranges: list[dict[str, str]]) -> bool:
    for item in ranges:
        start = time.fromisoformat(item["start"])
        end = time.fromisoformat(item["end"])
        if start <= value < end:
            return True
    return False
