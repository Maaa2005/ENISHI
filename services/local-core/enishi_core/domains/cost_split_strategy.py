"""`cost.split` の戦略（Phase D）。

`next_action` はこのモジュールの中核であり、**副作用を一切持たない純粋関数**である。

- 受け取るのは自分の `CloneAgent` と、双方が見てよい公開情報（`OfferState` / `total_amount` /
  `proposed_share`）だけ。相手の `CloneAgent` は受け取らない（型シグネチャで担保する）。
- `Session` を受け取らない。DBアクセス・commit を一切行わない。
- `proposed_share` は人間が明示した initiator の初期要求額であり、
  REQUEST メッセージとして最初から双方に公開されている値なので、`state` と同様に「公開情報」として
  渡してよい（`domains/base.py` 通り、responder の予算・留保価格・効用パラメータのような
  private な値ではない）。initiator の要求下限 `L = min(L_policy, proposed_share)` を
  ラウンドをまたいで一定に保つために必要（`my_last_offer` は譲歩とともに変化するため、
  そこから逆算すると L 自体が徐々に切り下がってしまい「留保価格の不可侵」が壊れる）。

`Session` が必要な判定（`approval_required` など）は、ドライバ（`cost_split.py` の
`run_cost_split_negotiation`）側で先に評価し、その結果（bool）だけを
`high_value_approval_required` 引数として渡す。
"""

from dataclasses import dataclass
from typing import Any, Literal

from enishi_core.models import CloneAgent

Role = Literal["initiator", "responder"]


@dataclass(frozen=True)
class OfferState:
    """交渉の公開状態。ここに入ってよいのは双方が見てよい情報だけ。"""

    round_number: int
    standing_offer: float  # 相手が現在提示している x（responder の負担額）
    my_last_offer: float | None  # 自分が直前に出した x（まだ出していなければ None）


@dataclass(frozen=True)
class StrategyAction:
    kind: Literal["accept", "counter", "escalate", "reject"]
    amount: float | None  # accept/counter のとき
    reason_codes: list[str]  # escalate/reject のとき（公開理由へ変換する前の内部コード）


def _cost_split_policy(clone: CloneAgent) -> dict[str, Any]:
    raw = clone.policy_profile.get("cost_split", {})
    policy = raw if isinstance(raw, dict) else {}
    return {
        "max_auto_accept_amount": float(policy.get("max_auto_accept_amount", 5000.0)),
        "max_negotiable_amount": float(policy.get("max_negotiable_amount", 30000.0)),
        "reservation_ratio": float(policy.get("reservation_ratio", 0.5)),
        "concession_ratio": float(policy.get("concession_ratio", 0.5)),
    }


def _cost_split_preferred_ratio(clone: CloneAgent) -> float:
    raw = clone.preference_profile.get("cost_split", {})
    preference = raw if isinstance(raw, dict) else {}
    return float(preference.get("preferred_ratio", 0.5))


def _responder_action(
    clone: CloneAgent,
    total_amount: float,
    state: OfferState,
    high_value_approval_required: bool,
) -> StrategyAction:
    policy = _cost_split_policy(clone)
    reservation_ratio = policy["reservation_ratio"]
    concession_ratio = policy["concession_ratio"]
    max_negotiable_amount = policy["max_negotiable_amount"]
    preferred_ratio = min(_cost_split_preferred_ratio(clone), reservation_ratio)

    reservation = round(total_amount * reservation_ratio, 2)  # U
    opening = round(total_amount * preferred_ratio, 2)  # open_r
    x_r = state.my_last_offer if state.my_last_offer is not None else opening
    standing = state.standing_offer

    if standing <= x_r:
        return StrategyAction(kind="accept", amount=standing, reason_codes=[])

    if standing > reservation:
        if standing <= max_negotiable_amount or high_value_approval_required:
            return StrategyAction(
                kind="escalate", amount=None, reason_codes=["cost_share_exceeds_reservation"]
            )
        return StrategyAction(kind="reject", amount=None, reason_codes=["cost_share_exceeds_limit"])

    new_x_r = round(min(reservation, x_r + (standing - x_r) * concession_ratio), 2)
    return StrategyAction(kind="counter", amount=new_x_r, reason_codes=[])


def _initiator_action(
    clone: CloneAgent,
    total_amount: float,
    proposed_share: float,
    state: OfferState,
) -> StrategyAction:
    policy = _cost_split_policy(clone)
    reservation_ratio = policy["reservation_ratio"]
    concession_ratio = policy["concession_ratio"]

    l_policy = round(total_amount * (1 - reservation_ratio), 2)
    # 人間が明示した proposed_share より高い額を、エージェントが勝手に要求し直してはならない。
    floor = min(l_policy, proposed_share)  # L
    x_i = state.my_last_offer if state.my_last_offer is not None else proposed_share
    standing = state.standing_offer

    if standing >= x_i:
        return StrategyAction(kind="accept", amount=standing, reason_codes=[])

    # E1: 自分は既に下限 L まで譲歩済み（x_i == L）だが、相手の提示はまだ L に届いていない。
    # これ以上譲れる余地がない。「相手の提示が自分の下限に届かない」は価値判断であり、
    # reject（エージェントが自動で打ち切る）ではなく escalate（所有者に返す）が
    # ENISHI の思想として正しい（responder 側の reject は max_negotiable_amount 超過という
    # 明示的なポリシー上限があるので別扱い）。
    if x_i <= floor and standing < floor:
        return StrategyAction(
            kind="escalate", amount=None, reason_codes=["cost_share_below_reservation"]
        )

    candidate = max(floor, x_i - (x_i - standing) * concession_ratio)
    candidate = round(candidate, 2)

    if candidate <= standing:
        return StrategyAction(kind="accept", amount=standing, reason_codes=[])

    return StrategyAction(kind="counter", amount=candidate, reason_codes=[])


def next_action(
    *,
    clone: CloneAgent,
    role: Role,
    total_amount: float,
    proposed_share: float,
    state: OfferState,
    high_value_approval_required: bool = False,
) -> StrategyAction:
    """次の一手を決める純粋関数。DBアクセス・相手クローンへの参照を一切持たない。

    `high_value_approval_required` は `services.policies.approval_required` の結果を
    ドライバが事前に評価して渡す（Session が要る判定を関数の外へ出すため）。
    """
    if role == "responder":
        return _responder_action(clone, total_amount, state, high_value_approval_required)
    return _initiator_action(clone, total_amount, proposed_share, state)
