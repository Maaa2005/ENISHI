"""割り勘ドメイン（Phase B）。

複数人で発生した費用の分担額の合意を、決定的な譲歩ロジックで交渉する（LLM不使用）。
支払いの実行・外部決済連携は一切行わない（合意の生成まで）。

既存2ドメインは離散候補集合の交差（meeting）と閾値比較（task）という二値判定だったのに対し、
`cost.split` は連続値の譲歩（効用の理想点と留保価格の間で歩み寄る）という第三の型を実例にする。

最小情報の原則: responder は自分の予算・留保価格・効用パラメータを一切メッセージに載せない。
送ってよいのは対案の金額（`proposed_share`）と `public_reason` だけ。
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from enishi_core.domains.base import BaseDecisionDomain, DomainRequest, NegotiationRequestLike
from enishi_core.domains.common import (
    append_message,
    create_agreement,
    create_negotiation_approval,
    evaluate_common_guards,
    require_active_clone,
)
from enishi_core.domains.cost_split_strategy import (
    OfferState,
    StrategyAction,
    _cost_split_policy,
    _cost_split_preferred_ratio,
    next_action,
)
from enishi_core.errors import EnishiError
from enishi_core.models import (
    CloneAgent,
    MessageType,
    NegotiationDecision,
    NegotiationMessage,
    NegotiationSession,
    NegotiationStatus,
)
from enishi_core.services.policies import approval_required, delegation_enabled
from enishi_core.services.public_reasons import to_public_reason

INTENT_COST_SPLIT = "cost.split"

# _MAX_ROUNDS を増やさない・乱数を導入しない理由（Phase D 設計判断、D5）:
# 交互提示は譲歩幅そのものが留保価格を推定させる情報漏れを生む。ラウンドを重ねるほど
# 「この相手はあといくら出せるか」が相手のエージェントに読めてしまい、
# reservation_ratio をメッセージに載せない対策だけでは防ぎきれない（動的な漏れ）。
# 3点では譲歩曲線の外挿が難しく、漏れを実用上限定できる。
# 乱数化で漏れを薄める案もあるが、ENISHI の「決定的で監査可能」という原則と衝突するため採らない。
_MAX_ROUNDS = 3


class CostSplitPayload(BaseModel):
    """`cost.split` の payload（initiator が送る依頼）。"""

    title: str = Field(min_length=1, max_length=500)
    total_amount: float = Field(gt=0)
    currency: str = Field(default="JPY", min_length=3, max_length=3)
    proposed_share: float = Field(ge=0)
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def validate_share_within_total(self) -> "CostSplitPayload":
        if self.proposed_share > self.total_amount:
            raise ValueError("proposed_share must not exceed total_amount")
        return self


@dataclass(frozen=True)
class CostSplitRequest:
    initiator_user_id: str
    responder_user_id: str
    title: str
    total_amount: float
    currency: str
    proposed_share: float
    deadline: str | None = None


class CostSplitDomain(BaseDecisionDomain):
    """割り勘ドメイン（連続値の譲歩）。"""

    intent = INTENT_COST_SPLIT
    delegation_key: str | None = "cost_split_negotiation"
    supports_remote = True
    payload_model = CostSplitPayload

    def validate_request(self, body: NegotiationRequestLike) -> DomainRequest:
        try:
            payload = CostSplitPayload.model_validate(body.payload)
        except ValidationError as exc:
            raise EnishiError(
                code="INVALID_NEGOTIATION_PAYLOAD",
                message=(
                    "cost.split には title, total_amount, proposed_share が必要です"
                    "（proposed_share は total_amount 以下）。"
                ),
                status_code=422,
                details={"intent": body.intent},
            ) from exc
        return CostSplitRequest(
            initiator_user_id=body.initiator_user_id,
            responder_user_id=body.responder_user_id,
            title=payload.title,
            total_amount=payload.total_amount,
            currency=payload.currency,
            proposed_share=payload.proposed_share,
            deadline=payload.deadline,
        )

    def topic_of(self, request: DomainRequest) -> str:
        assert isinstance(request, CostSplitRequest)
        return request.title

    def start(self, session_db: Session, request: DomainRequest) -> NegotiationSession:
        assert isinstance(request, CostSplitRequest)
        return run_cost_split_negotiation(
            session_db,
            initiator_user_id=request.initiator_user_id,
            responder_user_id=request.responder_user_id,
            title=request.title,
            total_amount=request.total_amount,
            currency=request.currency,
            proposed_share=request.proposed_share,
            deadline=request.deadline,
        )

    def build_remote_request_payload(self, request: dict[str, Any]) -> dict[str, Any]:
        """Relay経由の初回REQUESTのワイヤpayload（Phase F5-b）。"""
        return {
            "intent": INTENT_COST_SPLIT,
            "title": request["title"],
            "total_amount": request["total_amount"],
            "currency": request.get("currency") or "JPY",
            "proposed_share": request["proposed_share"],
            "deadline": request.get("deadline"),
        }

    def derive_own_position(
        self,
        session_db: Session,
        clone: CloneAgent,
        request_payload: dict[str, Any],
        peer_agent_id: str,
    ) -> dict[str, Any]:
        """自分側の私的な立ち位置（Phase F5-b）。送信しないローカル専用データ。

        `session_db` は現状このドメインでは使わない（ポリシー/選好は `clone` のプロファイルへ
        直接持つため）。他ドメイン（`meeting_schedule`）の disclosure policy 参照のように、
        将来 `session_db` を要する拡張が入りうるためシグネチャには残す。
        """
        policy = _cost_split_policy(clone)
        preferred_ratio = min(_cost_split_preferred_ratio(clone), policy["reservation_ratio"])
        return {
            "title": request_payload["title"],
            "total_amount": float(request_payload["total_amount"]),
            "currency": request_payload.get("currency") or "JPY",
            "deadline": request_payload.get("deadline"),
            "proposed_share": float(request_payload["proposed_share"]),
            "reservation_ratio": policy["reservation_ratio"],
            "preferred_ratio": preferred_ratio,
            "concession_ratio": policy["concession_ratio"],
            "max_auto_accept_amount": policy["max_auto_accept_amount"],
            "max_negotiable_amount": policy["max_negotiable_amount"],
        }

    def build_remote_propose_delta(self, own_position: dict[str, Any]) -> dict[str, Any]:
        """初回PROPOSEのwire delta（Phase F5-b）。自分の初期提示額のみ。"""
        return {"proposed_share": own_position["proposed_share"]}

    def decide_remote_reply(
        self,
        clone: CloneAgent,
        own_position: dict[str, Any],
        received_public: dict[str, Any],
        *,
        role: str,
        round_number: int,
        peer_personal_agent_id: str,
        delegation_enabled: bool,
        high_value_approval_required: bool,
        own_last_delta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """相手の提示に対する次の一手を決める（Phase F5-b）。

        `cost_split_strategy.next_action` をそのまま呼ぶ（判断ロジックは書き直さない）。
        `Session` を要する判定（委任・`high_value` 承認要否）はドライバが先に評価し、
        bool だけをここへ渡す既存の設計を踏襲する。
        """
        base_payload = {
            "title": own_position.get("title", ""),
            "total_amount": own_position.get("total_amount"),
            "currency": own_position.get("currency") or "JPY",
            "deadline": own_position.get("deadline"),
        }
        total_amount = float(own_position["total_amount"])
        proposed_share = float(own_position["proposed_share"])
        standing = float(received_public.get("proposed_share", proposed_share))
        my_last_offer: float | None = None
        if own_last_delta is not None and "proposed_share" in own_last_delta:
            my_last_offer = float(own_last_delta["proposed_share"])

        guard = evaluate_common_guards(
            clone=clone,
            delegation_enabled=delegation_enabled,
            peer_personal_agent_id=peer_personal_agent_id,
            not_delegated_reason_code="cost_split_negotiation_not_delegated",
        )
        guard_reason_codes = [*guard.pre_reason_codes, *guard.post_reason_codes]
        evidence = {
            **guard.evidence,
            "standing_offer": round(standing, 2),
            "round_number": round_number,
        }

        def approval_raw(agreed_share: float) -> dict[str, Any]:
            return {
                **base_payload,
                "agreed_share": round(agreed_share, 2),
                "standing_offer": round(standing, 2),
                "round_number": round_number,
            }

        if guard_reason_codes:
            return {
                "outcome": "approval_required",
                "reason_codes": guard_reason_codes,
                "evidence": evidence,
                "confidence": guard.confidence,
                "policy_version": clone.version,
                "reply_delta": {},
                "agreement_value": None,
                "approval_raw": approval_raw(standing),
                "proposed_action": "ACCEPT",
            }

        state = OfferState(
            round_number=round_number,
            standing_offer=round(standing, 2),
            my_last_offer=my_last_offer,
        )
        action: StrategyAction = next_action(
            clone=clone,
            role=role,  # type: ignore[arg-type]
            total_amount=total_amount,
            proposed_share=proposed_share,
            state=state,
            high_value_approval_required=high_value_approval_required,
        )

        if action.kind == "counter" and round_number >= _MAX_ROUNDS:
            # D3と同じ打ち切りルール（run_cost_split_negotiation参照）:
            # ラウンド上限に達しても交差しなかった場合は、黙って妥協を飲まず
            # 手番のエージェントが自分の所有者へ承認エスカレーションする。
            # next_action 自体は書き換えず、ドライバ相当のこの関数が結果をラップする。
            action = StrategyAction(
                kind="escalate", amount=None, reason_codes=["no_agreement_within_rounds"]
            )

        if action.kind == "accept":
            agreed_share = round(action.amount if action.amount is not None else standing, 2)
            return {
                "outcome": "auto_accept",
                "reason_codes": ["cost_split_within_position"],
                "evidence": evidence,
                "confidence": guard.confidence,
                "policy_version": clone.version,
                "reply_delta": {"agreed_share": agreed_share},
                "agreement_value": {**base_payload, "agreed_share": agreed_share},
                "approval_raw": {},
                "proposed_action": "ACCEPT",
            }

        if action.kind == "counter":
            assert action.amount is not None
            new_offer = round(action.amount, 2)
            return {
                "outcome": "counter",
                "reason_codes": ["cost_split_concession"],
                "evidence": evidence,
                "confidence": guard.confidence,
                "policy_version": clone.version,
                "reply_delta": {"proposed_share": new_offer},
                "agreement_value": None,
                "approval_raw": {},
                "proposed_action": "COUNTER",
            }

        if action.kind == "escalate":
            reason = (
                action.reason_codes[0] if action.reason_codes else "cost_split_requires_approval"
            )
            return {
                "outcome": "approval_required",
                "reason_codes": [reason],
                "evidence": evidence,
                "confidence": guard.confidence,
                "policy_version": clone.version,
                "reply_delta": {},
                "agreement_value": None,
                "approval_raw": approval_raw(standing),
                "proposed_action": "ACCEPT",
            }

        # reject
        reason = action.reason_codes[0] if action.reason_codes else "cost_share_exceeds_limit"
        return {
            "outcome": "reject",
            "reason_codes": [reason],
            "evidence": evidence,
            "confidence": guard.confidence,
            "policy_version": clone.version,
            "reply_delta": {"code": _reason_code_to_delta_code(reason)},
            "agreement_value": None,
            "approval_raw": {},
            "proposed_action": "ACCEPT",
        }

    def remote_agreement_payload(self, agreed: dict[str, Any]) -> dict[str, Any]:
        """遠隔交渉合意の agreed_payload（Phase F5-b）。"""
        return _agreed_payload(
            title=str(agreed.get("title", "")),
            total_amount=float(agreed.get("total_amount", 0.0)),
            currency=str(agreed.get("currency") or "JPY"),
            agreed_share=float(agreed.get("agreed_share", 0.0)),
            deadline=agreed.get("deadline"),
        )

    def agreement_value_from_accept_delta(
        self, delta: dict[str, Any], request_payload: dict[str, Any]
    ) -> Any:
        """相手のACCEPT deltaから合意値を取り出す（Phase F5-b）。

        `agreed_share` はdelta由来（相手が実際にACCEPTした額）、それ以外
        （title/total_amount/currency/deadline）はこのセッションのREQUEST payload
        （公開済みの文脈値）から補う。
        """
        return {
            "title": request_payload.get("title", ""),
            "total_amount": request_payload.get("total_amount"),
            "currency": request_payload.get("currency") or "JPY",
            "deadline": request_payload.get("deadline"),
            "agreed_share": delta.get("agreed_share"),
        }

    def approval_context(self, raw: dict[str, Any]) -> dict[str, Any]:
        """承認payloadの `proposal` / `public_context`（Phase F5-b）。

        留保価格・効用パラメータ（`reservation_ratio` 等）は `raw` に含まれない
        （`decide_remote_reply` がそもそも積まない）ため、ここでも露出しない。
        """
        proposal = {
            "title": raw.get("title", ""),
            "total_amount": raw.get("total_amount"),
            "currency": raw.get("currency") or "JPY",
            "deadline": raw.get("deadline"),
            "agreed_share": raw.get("agreed_share"),
        }
        public_context = {
            "standing_offer": raw.get("standing_offer"),
            "round_number": raw.get("round_number"),
        }
        return {"proposal": proposal, "public_context": public_context}

    def approval_reply(
        self,
        *,
        approved: bool,
        target_status: str,
        proposal: dict[str, Any],
        public_context: dict[str, Any],
        override: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """承認解決の結果からwireメッセージを組み立てる（Phase F5-b）。"""
        if not approved:
            code = "HUMAN_REJECTED" if target_status == "rejected" else "APPROVAL_EXPIRED"
            return {"message_type": "REJECT", "delta": {"code": code}, "agreement_value": None}

        agreed_share = proposal.get("agreed_share")
        if override is not None and override.get("agreed_share") is not None:
            agreed_share = override["agreed_share"]
        if agreed_share is None:
            raise EnishiError(
                code="INVALID_APPROVAL_SELECTION",
                message="承認する分担額を確認できません。",
                status_code=422,
            )
        agreed_share = round(float(agreed_share), 2)

        agreement_value = {
            "title": proposal.get("title", ""),
            "total_amount": proposal.get("total_amount"),
            "currency": proposal.get("currency") or "JPY",
            "deadline": proposal.get("deadline"),
            "agreed_share": agreed_share,
        }
        return {
            "message_type": "ACCEPT",
            "delta": {"agreed_share": agreed_share},
            "agreement_value": agreement_value,
        }


def _reason_code_to_delta_code(reason_code: str) -> str:
    return reason_code.upper()


def _agreed_payload(
    *,
    title: str,
    total_amount: float,
    currency: str,
    agreed_share: float,
    deadline: str | None,
) -> dict[str, Any]:
    return {
        "intent": INTENT_COST_SPLIT,
        "title": title,
        "total_amount": total_amount,
        "currency": currency,
        "agreed_share": agreed_share,
        "deadline": deadline,
    }


def run_cost_split_negotiation(
    session_db: Session,
    initiator_user_id: str,
    responder_user_id: str,
    title: str,
    total_amount: float,
    currency: str,
    proposed_share: float,
    deadline: str | None = None,
) -> NegotiationSession:
    """割り勘の分担額を決定的に交渉する（連続値の譲歩、LLM不使用）。"""
    initiator = require_active_clone(session_db, initiator_user_id)
    responder = require_active_clone(session_db, responder_user_id)

    request_payload: dict[str, Any] = {
        "intent": INTENT_COST_SPLIT,
        "title": title,
        "total_amount": total_amount,
        "currency": currency,
        "proposed_share": proposed_share,
        "deadline": deadline,
    }

    negotiation = NegotiationSession(
        initiator_clone_id=initiator.id,
        responder_clone_id=responder.id,
        intent=INTENT_COST_SPLIT,
        topic=title,
    )
    session_db.add(negotiation)
    session_db.flush()

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
            intent=INTENT_COST_SPLIT,
            payload=payload,
            delta=delta,
        )

    add_message(initiator, responder, MessageType.REQUEST, payload=request_payload)

    responder_policy = _cost_split_policy(responder)
    max_auto_accept_amount = responder_policy["max_auto_accept_amount"]

    offer = round(proposed_share, 2)

    # 事前ガード（全ドメイン共通・enishi_core.domains.common.evaluate_common_guards）
    # 委任OFF / confidence閾値未満 / relationship が承認要求 -> 承認エスカレーション。
    # ローカル交渉には relay 経由の相手 personal agent id が無いため、
    # 関係性ポリシーの照合キーには initiator のクローンIDを代用する。
    delegation_ok = delegation_enabled(
        session_db, responder.user_id, "cost_split_negotiation", default=True
    )
    guard = evaluate_common_guards(
        clone=responder,
        delegation_enabled=delegation_ok,
        peer_personal_agent_id=initiator.id,
        not_delegated_reason_code="cost_split_negotiation_not_delegated",
    )
    guard_reason_codes = [*guard.pre_reason_codes, *guard.post_reason_codes]
    if guard_reason_codes:
        create_negotiation_approval(
            session_db,
            responder,
            negotiation,
            _agreed_payload(
                title=title,
                total_amount=total_amount,
                currency=currency,
                agreed_share=offer,
                deadline=deadline,
            ),
            reason=guard_reason_codes[0],
            sequence=len(messages) + 1,
        )
        return negotiation

    if offer <= max_auto_accept_amount:
        add_message(responder, initiator, MessageType.ACCEPT, delta={"agreed_share": offer})
        negotiation.status = NegotiationStatus.AGREED.value
        negotiation.result = {"agreed_share": offer, "rounds": 1}
        create_agreement(
            session_db,
            negotiation,
            _agreed_payload(
                title=title,
                total_amount=total_amount,
                currency=currency,
                agreed_share=offer,
                deadline=deadline,
            ),
        )
        session_db.commit()
        session_db.refresh(negotiation)
        return negotiation

    def record_decision(
        decider: CloneAgent,
        *,
        outcome: str,
        reason_codes: list[str],
        round_number: int,
        standing_offer: float,
    ) -> None:
        # D6: evidence には公開可能な集約値だけを入れる（留保価格そのものは入れない）。
        session_db.add(
            NegotiationDecision(
                session_id=negotiation.id,
                clone_id=decider.id,
                policy_version=decider.version,
                outcome=outcome,
                reason_codes=reason_codes,
                evidence={"standing_offer": standing_offer, "round_number": round_number},
                confidence=max(0.0, min(1.0, float(decider.confidence_score))),
            )
        )

    def escalate(decider: CloneAgent, *, reason: str, round_number: int, standing: float) -> None:
        record_decision(
            decider,
            outcome="approval_required",
            reason_codes=[reason],
            round_number=round_number,
            standing_offer=standing,
        )
        create_negotiation_approval(
            session_db,
            decider,
            negotiation,
            _agreed_payload(
                title=title,
                total_amount=total_amount,
                currency=currency,
                agreed_share=round(standing, 2),
                deadline=deadline,
            ),
            reason=reason,
            sequence=len(messages) + 1,
        )

    def reject(decider: CloneAgent, other: CloneAgent, *, reason: str, round_number: int) -> None:
        record_decision(
            decider,
            outcome="reject",
            reason_codes=[reason],
            round_number=round_number,
            standing_offer=round(offer, 2),
        )
        add_message(
            decider,
            other,
            MessageType.REJECT,
            payload={"public_reason": to_public_reason([reason])},
            delta={"code": _reason_code_to_delta_code(reason)},
        )
        negotiation.status = NegotiationStatus.FAILED.value
        negotiation.result = {"code": _reason_code_to_delta_code(reason), "rounds": round_number}
        session_db.commit()
        session_db.refresh(negotiation)

    # ZOPA（合意可能領域）の事前判定（ドライバの最適化としてのみ実装。next_action には持ち込まない）
    # L は initiator の私的情報、U は responder の私的情報だが、ローカル交渉ではドライバに
    # 両者のクローンが揃っているためこの判定だけは直接行える。リモートでは行えない。
    #
    # L = min(L_policy, proposed_share) は常に proposed_share(=offer) 以下になるよう
    # クランプされているため（人間の入力より高い額を要求し直さないため）、L > U ならば
    # 必ず offer > U でもある。つまり ZOPA が無いケースは、ラウンド1の responder 判定
    # （standing > U）と常に同じ入り口に到達する。ここでの事前判定はラウンド1と同じ
    # reject/escalate の分岐（max_negotiable_amount / high_value 承認）を踏襲しつつ、
    # 無駄なラウンドを回さずに理由コード "no_zone_of_agreement" を記録するためのものである。
    initiator_policy = _cost_split_policy(initiator)
    zopa_floor = min(
        round(total_amount * (1 - initiator_policy["reservation_ratio"]), 2), offer
    )
    zopa_ceiling = round(total_amount * responder_policy["reservation_ratio"], 2)
    if zopa_floor > zopa_ceiling:
        if offer <= responder_policy["max_negotiable_amount"] or approval_required(
            session_db, responder.user_id, "high_value"
        ):
            escalate(
                responder,
                reason="no_zone_of_agreement",
                round_number=1,
                standing=offer,
            )
        else:
            reject(
                responder,
                initiator,
                reason="cost_share_exceeds_limit",
                round_number=1,
            )
        return negotiation

    # 交互提示ドライバ（D2）。副作用（append_message/create_agreement/create_negotiation_approval/
    # commit）はここだけが持つ。next_action は純粋関数で、自分の clone と公開情報だけを見て
    # 次の一手を決める。
    standing = offer
    x_i: float | None = offer  # initiator の直前の提示（＝proposed_share から開始）
    x_r: float | None = None  # responder はまだ何も提示していない
    turn: str = "responder"

    for round_number in range(1, _MAX_ROUNDS + 1):
        acting = responder if turn == "responder" else initiator
        other = initiator if turn == "responder" else responder
        my_last_offer = x_r if turn == "responder" else x_i

        high_value_approval_required = False
        if turn == "responder":
            high_value_approval_required = approval_required(
                session_db, responder.user_id, "high_value"
            )

        state = OfferState(
            round_number=round_number,
            standing_offer=round(standing, 2),
            my_last_offer=my_last_offer,
        )
        action: StrategyAction = next_action(
            clone=acting,
            role=turn,  # type: ignore[arg-type]
            total_amount=total_amount,
            proposed_share=offer,
            state=state,
            high_value_approval_required=high_value_approval_required,
        )

        if action.kind == "counter" and round_number == _MAX_ROUNDS:
            # D3: ラウンド上限に達しても交差しなかった場合は、黙って妥協を飲まず
            # 手番のエージェントが自分の所有者へ承認エスカレーションする。
            action = StrategyAction(
                kind="escalate", amount=None, reason_codes=["no_agreement_within_rounds"]
            )

        if action.kind == "accept":
            agreed_share = round(action.amount if action.amount is not None else standing, 2)
            add_message(acting, other, MessageType.ACCEPT, delta={"agreed_share": agreed_share})
            negotiation.status = NegotiationStatus.AGREED.value
            negotiation.result = {"agreed_share": agreed_share, "rounds": round_number}
            create_agreement(
                session_db,
                negotiation,
                _agreed_payload(
                    title=title,
                    total_amount=total_amount,
                    currency=currency,
                    agreed_share=agreed_share,
                    deadline=deadline,
                ),
            )
            session_db.commit()
            session_db.refresh(negotiation)
            return negotiation

        if action.kind == "escalate":
            escalate(
                acting,
                reason=action.reason_codes[0],
                round_number=round_number,
                standing=standing,
            )
            return negotiation

        if action.kind == "reject":
            reject(acting, other, reason=action.reason_codes[0], round_number=round_number)
            return negotiation

        # counter
        assert action.amount is not None
        new_offer = round(action.amount, 2)
        if turn == "responder":
            x_r = new_offer
        else:
            x_i = new_offer
        standing = new_offer
        add_message(
            acting,
            other,
            MessageType.COUNTER,
            payload={"public_reason": to_public_reason(["cost_split_concession"])},
            delta={"proposed_share": new_offer},
        )
        turn = "initiator" if turn == "responder" else "responder"

    session_db.commit()
    session_db.refresh(negotiation)
    return negotiation
