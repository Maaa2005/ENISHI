"""日程調整ドメイン（enishi.md §25, §27, §28）。

2クローン間の日程調整を決定的に実行する（LLM不使用）。
2通目以降のメッセージは差分だけをdeltaへ入れる（§25）。
交渉完了後、構造化方式とメール方式のトークン消費を実測して記録する（§28）。
"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from enishi_core.domains.base import BaseDecisionDomain, DomainRequest, NegotiationRequestLike
from enishi_core.domains.common import (
    DecisionEvaluation,
    DecisionOutcome,
    append_message,
    create_agreement,
    create_negotiation_approval,
    evaluate_common_guards,
    require_active_clone,
)
from enishi_core.domains.value_objects import DateRange, TimeRange
from enishi_core.errors import EnishiError
from enishi_core.models import (
    CloneAgent,
    MessageType,
    NegotiationDecision,
    NegotiationMessage,
    NegotiationSession,
    NegotiationStatus,
    TokenMetric,
    User,
)
from enishi_core.services.audit import log_event
from enishi_core.services.memories import exportable_memories
from enishi_core.services.peers import filter_memories_for_peer, get_disclosure_policy
from enishi_core.services.policies import delegation_enabled as delegation_enabled_policy
from enishi_core.services.scheduling import (
    Slot,
    candidate_slots,
    collect_busy,
    intersect_slots,
)
from enishi_core.services.token_counter import estimate_json_tokens, estimate_tokens

INTENT_MEETING_SCHEDULE = "meeting.schedule"
_MAX_ROUNDS = 3
_OFFER_SIZE = 5


class MeetingSchedulePayload(BaseModel):
    """`meeting.schedule` の payload（Phase B: ドメイン語彙はここへ閉じ込める）。"""

    topic: str = Field(min_length=1, max_length=500)
    duration_minutes: int = Field(ge=1, le=480)
    date_range: DateRange
    preferred_time_ranges: list[TimeRange] = Field(min_length=1)


@dataclass(frozen=True)
class MeetingScheduleRequest:
    initiator_user_id: str
    responder_user_id: str
    topic: str
    duration_minutes: int
    date_range: dict[str, str]
    preferred_time_ranges: list[dict[str, str]]


class MeetingScheduleDomain(BaseDecisionDomain):
    """会議日程調整ドメイン（多ラウンド提案・逆提案）。"""

    intent = INTENT_MEETING_SCHEDULE
    # meeting の run_negotiation は現状 delegation を見ていないため、
    # ここで新たに delegation_key を見に行かない（挙動が変わる）。
    delegation_key: str | None = None
    supports_remote = True
    payload_model = MeetingSchedulePayload

    def validate_request(self, body: NegotiationRequestLike) -> DomainRequest:
        try:
            payload = MeetingSchedulePayload.model_validate(body.payload)
        except ValidationError as exc:
            raise EnishiError(
                code="INVALID_NEGOTIATION_PAYLOAD",
                message=(
                    "meeting.schedule には topic, duration_minutes, date_range, "
                    "preferred_time_ranges が必要です。"
                ),
                status_code=422,
                details={"intent": body.intent},
            ) from exc
        return MeetingScheduleRequest(
            initiator_user_id=body.initiator_user_id,
            responder_user_id=body.responder_user_id,
            topic=payload.topic,
            duration_minutes=payload.duration_minutes,
            date_range=payload.date_range.model_dump(),
            preferred_time_ranges=[r.model_dump() for r in payload.preferred_time_ranges],
        )

    def topic_of(self, request: DomainRequest) -> str:
        assert isinstance(request, MeetingScheduleRequest)
        return request.topic

    def start(self, session_db: Session, request: DomainRequest) -> NegotiationSession:
        assert isinstance(request, MeetingScheduleRequest)
        return run_negotiation(
            session_db,
            initiator_user_id=request.initiator_user_id,
            responder_user_id=request.responder_user_id,
            topic=request.topic,
            duration_minutes=request.duration_minutes,
            date_range=request.date_range,
            preferred_time_ranges=request.preferred_time_ranges,
        )

    def evaluate_decision(self, **kwargs: Any) -> DecisionEvaluation:
        """E3-a: ローカル/リモート両ドライバが同じ判断コードへレジストリ経由でたどり着く継ぎ目。"""
        return evaluate_meeting_schedule(**kwargs)

    def build_remote_request_payload(self, request: dict[str, Any]) -> dict[str, Any]:
        """Relay経由の初回REQUESTのワイヤpayload（Phase F1: `remote_negotiation.py` から移設）。"""
        return {
            "intent": INTENT_MEETING_SCHEDULE,
            "topic": request["topic"],
            "duration_minutes": request["duration_minutes"],
            "date_range": request["date_range"],
            "preferred_time_ranges": request["preferred_time_ranges"],
            "timezone": request["timezone"],
        }

    def derive_own_position(
        self,
        session_db: Session,
        clone: CloneAgent,
        request_payload: dict[str, Any],
        peer_agent_id: str,
    ) -> dict[str, Any]:
        """自分側の候補スロット一覧（Phase F1: `remote_negotiation._own_candidates` を移設）。"""
        policy = get_disclosure_policy(session_db, peer_agent_id)
        if not policy.share_schedule:
            raise EnishiError(
                code="DISCLOSURE_POLICY_DENIED",
                message="このピアには日程候補を公開しません。",
                status_code=403,
                details={"peer_agent_id": peer_agent_id},
            )
        memories = filter_memories_for_peer(
            exportable_memories(session_db, clone.user_id), policy
        )
        user = session_db.get(User, clone.user_id)
        timezone = user.timezone if user else "UTC"
        busy = collect_busy(memories, timezone)
        candidates = candidate_slots(
            dict(request_payload["date_range"]),
            list(request_payload["preferred_time_ranges"]),
            int(request_payload["duration_minutes"]),
            busy,
            timezone,
        )
        return {"candidates": candidates}

    def decide_remote_reply(
        self, own_position: dict[str, Any], received_public: dict[str, Any]
    ) -> dict[str, Any]:
        """共通スロットの交差（Phase F1: `remote_negotiation._handle_envelope` から移設）。"""
        own = own_position.get("candidates", [])
        received = [dict(s) for s in received_public.get("candidate_slots", [])]
        common = intersect_slots(own, received)
        return {
            "common_slot_count": len(common),
            "selected_slot": common[0] if common else None,
            "counter_offer": own[:_OFFER_SIZE],
        }

    def remote_agreement_payload(self, agreed: dict[str, Any]) -> dict[str, Any]:
        """遠隔交渉合意の agreed_payload（Phase F1: `_meeting_agreement_payload` を移設）。"""
        return {"selected_slot": dict(agreed)}

    def approval_context(self, raw: dict[str, Any]) -> dict[str, Any]:
        """承認payloadの `proposal` / `public_context`（Phase F2）。

        `selected_slot` / `candidate_slots` はどちらも日時の範囲だけを持ち、
        留保価格・効用パラメータのような私的情報は含まない。
        """
        selected_slot = raw.get("selected_slot")
        candidate_slots = list(raw.get("candidate_slots") or [])
        return {
            "proposal": {"selected_slot": dict(selected_slot)} if selected_slot else {},
            "public_context": {"candidate_slots": candidate_slots},
        }


def _slot_label(slot: Slot) -> str:
    return f"{slot['start']}〜{slot['end'].split('T')[-1]}"


def build_email_transcript(
    topic: str,
    duration_minutes: int,
    offers: list[list[Slot]],
    selected_slot: Slot | None,
) -> list[str]:
    """同じ交渉をメール往復で行った場合の文面を組み立てる（テンプレート、LLM不使用）。"""
    emails: list[str] = [
        f"お世話になっております。\n\n"
        f"{topic}について{duration_minutes}分ほどお時間をいただきたく、"
        f"ご連絡いたしました。\n"
        f"ご都合のよい日時の候補をいくつかお知らせいただけますでしょうか。\n\n"
        f"何卒よろしくお願いいたします。"
    ]
    for offer in offers:
        lines = "\n".join(f"・{_slot_label(slot)}" for slot in offer)
        emails.append(
            f"ご連絡ありがとうございます。\n\n"
            f"こちらの都合のよい候補は以下のとおりです。\n{lines}\n\n"
            f"上記でご都合いかがでしょうか。\n"
            f"よろしくお願いいたします。"
        )
    if selected_slot is not None:
        emails.append(
            f"ありがとうございます。\n\n"
            f"それでは {_slot_label(selected_slot)} でお願いいたします。\n"
            f"当日はどうぞよろしくお願いいたします。"
        )
    else:
        emails.append(
            "ご確認ありがとうございました。\n\n"
            "あいにく都合の合う時間が見つかりませんでした。\n"
            "別の週で改めて調整させてください。\n"
            "よろしくお願いいたします。"
        )
    return emails


def _record_metrics(
    session_db: Session,
    negotiation: NegotiationSession,
    messages: list[NegotiationMessage],
    offers: list[list[Slot]],
    selected_slot: Slot | None,
    topic: str,
    duration_minutes: int,
) -> None:
    """交渉の実測トークンを記録する（§28。固定値ではなく生成物から計算する）。"""
    structured_total = sum(
        estimate_json_tokens(m.payload) + estimate_json_tokens(m.delta) for m in messages
    )
    emails = build_email_transcript(topic, duration_minutes, offers, selected_slot)
    email_total = sum(estimate_tokens(email) for email in emails)

    session_db.add(
        TokenMetric(
            session_id=negotiation.id,
            method="structured",
            input_tokens=structured_total // 2,
            output_tokens=structured_total - structured_total // 2,
            llm_calls=0,
            message_count=len(messages),
        )
    )
    session_db.add(
        TokenMetric(
            session_id=negotiation.id,
            method="email",
            input_tokens=email_total // 2,
            output_tokens=email_total - email_total // 2,
            llm_calls=len(emails),
            message_count=len(emails),
        )
    )
    session_db.commit()


def run_negotiation(
    session_db: Session,
    initiator_user_id: str,
    responder_user_id: str,
    topic: str,
    duration_minutes: int,
    date_range: dict[str, str],
    preferred_time_ranges: list[dict[str, str]],
) -> NegotiationSession:
    """日程調整の交渉を同期実行する。日程計算はPythonコードで行う（§27）。"""
    initiator = require_active_clone(session_db, initiator_user_id)
    responder = require_active_clone(session_db, responder_user_id)

    initiator_user = session_db.get(User, initiator_user_id)
    responder_user = session_db.get(User, responder_user_id)
    initiator_timezone = initiator_user.timezone if initiator_user else "UTC"
    responder_timezone = responder_user.timezone if responder_user else "UTC"
    initiator_busy = collect_busy(
        exportable_memories(session_db, initiator_user_id), initiator_timezone
    )
    responder_busy = collect_busy(
        exportable_memories(session_db, responder_user_id), responder_timezone
    )
    initiator_candidates = candidate_slots(
        date_range,
        preferred_time_ranges,
        duration_minutes,
        initiator_busy,
        initiator_timezone,
    )
    responder_candidates = candidate_slots(
        date_range,
        preferred_time_ranges,
        duration_minutes,
        responder_busy,
        responder_timezone,
    )

    negotiation = NegotiationSession(
        initiator_clone_id=initiator.id,
        responder_clone_id=responder.id,
        intent=INTENT_MEETING_SCHEDULE,
        topic=topic,
    )
    session_db.add(negotiation)
    session_db.commit()
    session_db.refresh(negotiation)

    messages: list[NegotiationMessage] = []

    def add_message(
        sender: CloneAgent,
        receiver: CloneAgent,
        message_type: MessageType,
        payload: dict[str, Any] | None = None,
        delta: dict[str, Any] | None = None,
    ) -> NegotiationMessage:
        return append_message(
            session_db,
            negotiation,
            messages,
            sender=sender,
            receiver=receiver,
            message_type=message_type,
            intent=INTENT_MEETING_SCHEDULE,
            payload=payload,
            delta=delta,
        )

    # 初回のみ全体を送り、以降は差分のみdeltaで送る（§25）
    add_message(
        initiator,
        responder,
        MessageType.REQUEST,
        payload={
            "intent": INTENT_MEETING_SCHEDULE,
            "topic": topic,
            "duration_minutes": duration_minutes,
            "date_range": date_range,
            "preferred_time_ranges": preferred_time_ranges,
            "timezone": initiator_timezone,
        },
    )

    candidates_by_clone = {initiator.id: initiator_candidates, responder.id: responder_candidates}
    offers: list[list[Slot]] = []
    selected_slot: Slot | None = None
    rounds = 0

    current_offer = initiator_candidates[:_OFFER_SIZE]
    offers.append(current_offer)
    add_message(
        initiator, responder, MessageType.PROPOSE, delta={"candidate_slots": current_offer}
    )

    timezone_by_clone = {initiator.id: initiator_timezone, responder.id: responder_timezone}

    sender, receiver = initiator, responder
    for round_number in range(1, _MAX_ROUNDS + 1):
        rounds = round_number
        common = intersect_slots(candidates_by_clone[receiver.id], current_offer)
        if common:
            selected_slot = common[0]
            # E3-b: ACCEPTする直前に、所有者の delegation/confidence/relationship を通す
            # （E3-a の評価関数、`domains/README.md` の「戦略と進行の分離」参照）。
            # これは意図的な挙動変更である。ローカル交渉が所有者の権限を無視して
            # 自動合意していたのは「人間の価値観と権限を持つエージェント」という
            # ENISHI の定義に反するため（Phase E 仕様書 E3-b）。
            evaluation = evaluate_meeting_schedule(
                clone=receiver,
                delegation_enabled=delegation_enabled_policy(
                    session_db, receiver.user_id, "schedule_negotiation", default=True
                ),
                common_slot_count=len(common),
                selected_slot=selected_slot,
                peer_personal_agent_id=sender.id,
                timezone=timezone_by_clone.get(receiver.id, "UTC"),
            )
            session_db.add(
                NegotiationDecision(
                    session_id=negotiation.id,
                    clone_id=receiver.id,
                    policy_version=evaluation.policy_version,
                    outcome=evaluation.outcome,
                    reason_codes=evaluation.reason_codes,
                    evidence=evaluation.evidence,
                    confidence=evaluation.confidence,
                )
            )
            if evaluation.outcome != "auto_accept":
                reason = (
                    evaluation.reason_codes[0]
                    if evaluation.reason_codes
                    else "meeting_decision_requires_approval"
                )
                create_negotiation_approval(
                    session_db,
                    receiver,
                    negotiation,
                    {
                        "intent": INTENT_MEETING_SCHEDULE,
                        "topic": topic,
                        "duration_minutes": duration_minutes,
                        "selected_slot": selected_slot,
                    },
                    reason=reason,
                    sequence=len(messages) + 1,
                )
                break
            add_message(
                receiver, sender, MessageType.ACCEPT, delta={"selected_slot": selected_slot}
            )
            negotiation.status = NegotiationStatus.AGREED.value
            negotiation.result = {"selected_slot": selected_slot, "rounds": rounds}
            create_agreement(session_db, negotiation, negotiation.result)
            break
        if round_number == _MAX_ROUNDS:
            add_message(receiver, sender, MessageType.ERROR, delta={"code": "NO_AVAILABLE_SLOT"})
            negotiation.status = NegotiationStatus.FAILED.value
            negotiation.result = {"code": "NO_AVAILABLE_SLOT", "rounds": rounds}
            break
        counter_offer = candidates_by_clone[receiver.id][:_OFFER_SIZE]
        offers.append(counter_offer)
        add_message(
            receiver,
            sender,
            MessageType.COUNTER,
            payload={"public_reason": "no_common_slot"},
            delta={"candidate_slots": counter_offer},
        )
        current_offer = counter_offer
        sender, receiver = receiver, sender

    session_db.commit()
    session_db.refresh(negotiation)

    _record_metrics(
        session_db, negotiation, messages, offers, selected_slot, topic, duration_minutes
    )
    log_event(
        session_db,
        event_type="negotiation_completed",
        payload={
            "session_id": negotiation.id,
            "status": negotiation.status,
            "message_count": len(messages),
            "rounds": rounds,
        },
    )
    return negotiation


@dataclass(frozen=True)
class MeetingPreferenceEvaluation:
    reason_codes: list[str]
    meeting_auto_accept: bool | None
    evidence: dict[str, Any]


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


def _slot_start_time(
    selected_slot: dict[str, Any] | None, timezone: str = "UTC"
) -> time | None:
    if not selected_slot or not isinstance(selected_slot.get("start"), str):
        return None
    try:
        value = datetime.fromisoformat(str(selected_slot["start"]))
        if value.tzinfo is not None:
            value = value.astimezone(ZoneInfo(timezone))
        return value.time()
    except ValueError:
        return None


def _time_in_ranges(value: time, ranges: list[dict[str, str]]) -> bool:
    for item in ranges:
        start = time.fromisoformat(item["start"])
        end = time.fromisoformat(item["end"])
        if start <= value < end:
            return True
    return False


def evaluate_meeting_preferences(
    *,
    clone: CloneAgent,
    selected_slot: dict[str, Any] | None,
    timezone: str = "UTC",
) -> MeetingPreferenceEvaluation:
    """時間帯の好みと自動承諾ポリシーを評価する（ドメイン固有・共通ガードではない）。"""
    raw_meeting_policy = clone.policy_profile.get("meeting_schedule", {})
    meeting_auto_accept: bool | None = None
    if isinstance(raw_meeting_policy, dict) and "auto_accept" in raw_meeting_policy:
        raw_value = raw_meeting_policy["auto_accept"]
        if isinstance(raw_value, bool):
            meeting_auto_accept = raw_value

    reason_codes: list[str] = []
    if meeting_auto_accept is False:
        reason_codes.append("meeting_auto_accept_disabled")

    meeting_preferences = clone.preference_profile.get("meeting_schedule", {})
    preferred_ranges: list[dict[str, str]] = []
    avoid_ranges: list[dict[str, str]] = []
    if isinstance(meeting_preferences, dict):
        preferred_ranges = _valid_time_ranges(meeting_preferences.get("preferred_time_ranges"))
        avoid_ranges = _valid_time_ranges(meeting_preferences.get("avoid_time_ranges"))
    selected_time = _slot_start_time(selected_slot, timezone)
    within_preferred = selected_time is not None and (
        not preferred_ranges or _time_in_ranges(selected_time, preferred_ranges)
    )
    within_avoided = selected_time is not None and _time_in_ranges(selected_time, avoid_ranges)
    if preferred_ranges and not within_preferred:
        reason_codes.append("meeting_outside_preferred_time")
    if within_avoided:
        reason_codes.append("meeting_time_avoided")

    return MeetingPreferenceEvaluation(
        reason_codes=reason_codes,
        meeting_auto_accept=meeting_auto_accept,
        evidence={
            "meeting_auto_accept": meeting_auto_accept,
            "preferred_time_configured": bool(preferred_ranges),
            "selected_time_within_preference": within_preferred,
            "selected_time_avoided": within_avoided,
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
    """公開可能な集約値だけを根拠に、決定的な順序で判断する（E3-a）。

    `cost_split_strategy.next_action` と同じ思想の**純粋な評価関数**: 自分の `clone` と
    公開可能な集約値だけを受け取り、`Session` も相手の `CloneAgent` も受け取らない。
    ローカル（`run_negotiation`）とリモート（`services/remote_negotiation.py`）の両ドライバが
    `enishi_core.domains.get_domain("meeting.schedule")` 経由でここへたどり着くことで、
    「日程調整の判断」の二重化を構造的に解消する（進行＝ループはドライバ側に残す。E3-d）。

    薄いラッパだったものをここへ移した。共通ガードは `evaluate_common_guards`
    （`domains/common.py`）、会議固有の評価は `evaluate_meeting_preferences` が担う。
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

    outcome: DecisionOutcome
    if reason_codes:
        outcome = "approval_required"
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
