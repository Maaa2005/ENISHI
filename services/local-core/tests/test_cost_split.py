"""割り勘ドメイン（`cost.split`）のテスト（Phase B2）。

連続値の譲歩（効用の理想点と留保価格の間で歩み寄る）を検証する。
最小情報の原則（responder の予算・留保価格・効用パラメータをメッセージに載せない）は
test 5 で全メッセージを走査して確認する。
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

_FORBIDDEN_KEYS = {
    "reservation_ratio",
    "preferred_ratio",
    "concession_ratio",
    "max_auto_accept_amount",
    "max_negotiable_amount",
}


def _create_user(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post("/v1/users", json={"display_name": name}, headers=headers)
    assert response.status_code == 201
    return str(response.json()["id"])


def _activate_clone(client: TestClient, headers: dict[str, str], user_id: str) -> str:
    clone_response = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "割り勘交渉", "provider_type": "mock"},
        headers=headers,
    )
    assert clone_response.status_code == 200
    clone_id = str(clone_response.json()["id"])
    activated = client.post(f"/v1/clones/{clone_id}/activate", headers=headers)
    assert activated.status_code == 200
    return clone_id


def _set_cost_split_profile(
    clone_id: str,
    *,
    policy: dict[str, Any] | None = None,
    preference: dict[str, Any] | None = None,
) -> None:
    from enishi_core.database import get_session
    from enishi_core.models import CloneAgent

    session = next(get_session())
    try:
        clone = session.get(CloneAgent, clone_id)
        assert clone is not None
        if policy is not None:
            clone.policy_profile = {**clone.policy_profile, "cost_split": policy}
        if preference is not None:
            clone.preference_profile = {**clone.preference_profile, "cost_split": preference}
        session.commit()
    finally:
        session.close()


def _cost_split(
    client: TestClient,
    headers: dict[str, str],
    initiator_user_id: str,
    responder_user_id: str,
    *,
    title: str = "旅行費用",
    total_amount: float,
    proposed_share: float,
    currency: str = "JPY",
    deadline: str | None = None,
) -> dict[str, Any]:
    response = client.post(
        "/v1/negotiations",
        json={
            "intent": "cost.split",
            "initiator_user_id": initiator_user_id,
            "responder_user_id": responder_user_id,
            "payload": {
                "title": title,
                "total_amount": total_amount,
                "currency": currency,
                "proposed_share": proposed_share,
                "deadline": deadline,
            },
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _setup_pair(client: TestClient, headers: dict[str, str]) -> tuple[str, str, str]:
    """initiator_user_id, responder_user_id, responder_clone_id を返す。

    新規クローンは confidence_score が低く（bootstrap時のメモリ0件で 0.3）、
    共通ガード層の confidence 閾値（0.6）を割ってしまい常に承認エスカレーションになる。
    このファイルのシナリオはガード自体ではなく交渉ロジックを検証するため、
    responder のクローンを委任先として十分な confidence に引き上げておく。
    """
    initiator = _create_user(client, headers, "中村")
    responder = _create_user(client, headers, "田中")
    _activate_clone(client, headers, initiator)
    responder_clone_id = _activate_clone(client, headers, responder)

    from enishi_core.database import get_session
    from enishi_core.models import CloneAgent

    session = next(get_session())
    try:
        clone = session.get(CloneAgent, responder_clone_id)
        assert clone is not None
        clone.confidence_score = 0.9
        session.commit()
    finally:
        session.close()

    return initiator, responder, responder_clone_id


@pytest.fixture()
def pair(client: TestClient, auth_headers: dict[str, str]) -> tuple[str, str, str]:
    return _setup_pair(client, auth_headers)


def test_offer_within_auto_accept_agrees_in_one_round(
    client: TestClient, auth_headers: dict[str, str], pair: tuple[str, str, str]
) -> None:
    initiator, responder, _responder_clone_id = pair
    # デフォルト max_auto_accept_amount = 5000.0
    negotiation = _cost_split(
        client,
        auth_headers,
        initiator,
        responder,
        total_amount=20000.0,
        proposed_share=3000.0,
    )
    assert negotiation["status"] == "agreed"
    assert negotiation["result"]["agreed_share"] == 3000.0
    assert negotiation["result"]["rounds"] == 1

    agreements = client.get("/v1/agreements", headers=auth_headers).json()
    matching = [a for a in agreements if a["session_id"] == negotiation["id"]]
    assert len(matching) == 1
    assert matching[0]["agreed_payload"]["agreed_share"] == 3000.0
    assert matching[0]["agreed_payload"]["intent"] == "cost.split"


def test_continuous_concession_counters_between_target_and_offer(
    client: TestClient, auth_headers: dict[str, str], pair: tuple[str, str, str]
) -> None:
    initiator, responder, responder_clone_id = pair
    _set_cost_split_profile(
        responder_clone_id,
        policy={
            "max_auto_accept_amount": 1000.0,
            "max_negotiable_amount": 30000.0,
            "reservation_ratio": 0.5,
            "concession_ratio": 0.5,
        },
        preference={"preferred_ratio": 0.2},
    )
    # total=10000 -> reservation=5000, target(current)=2000
    # 1ラウンド目: offer(3000) > current(2000) かつ offer(3000) <= reservation(5000) -> COUNTER
    # current = min(5000, 2000 + (3000-2000)*0.5) = 2500（理想点2000と相手提案3000の間）
    # 2000<current<3000 のため2ラウンド目以降も収束せず、MAX_ROUNDSで強制ACCEPTとなる
    # （このテストは「連続値の譲歩が起きること」自体を検証する。最終的な収束経路は問わない）。
    negotiation = _cost_split(
        client,
        auth_headers,
        initiator,
        responder,
        total_amount=10000.0,
        proposed_share=3000.0,
    )

    messages = client.get(
        f"/v1/negotiations/{negotiation['id']}/messages", headers=auth_headers
    ).json()
    assert messages[0]["message_type"] == "REQUEST"
    first_counter = messages[1]
    assert first_counter["message_type"] == "COUNTER"
    proposed = first_counter["delta"]["proposed_share"]
    # 理想点(target=2000)と相手提案(offer=3000)の間にある連続値の譲歩
    assert 2000.0 < proposed < 3000.0
    assert proposed == 2500.0


def test_offer_exceeds_reservation_within_negotiable_escalates_to_approval(
    client: TestClient, auth_headers: dict[str, str], pair: tuple[str, str, str]
) -> None:
    initiator, responder, _responder_clone_id = pair
    # デフォルト: reservation_ratio=0.5, max_negotiable_amount=30000
    # total=10000 -> reservation=5000, offer=6000 (> reservation, <= max_negotiable)
    negotiation = _cost_split(
        client,
        auth_headers,
        initiator,
        responder,
        total_amount=10000.0,
        proposed_share=6000.0,
    )
    assert negotiation["status"] == "waiting_approval"
    assert negotiation["pending_approval_id"] is not None


def test_offer_exceeds_max_negotiable_and_high_value_disabled_rejects(
    client: TestClient, auth_headers: dict[str, str], pair: tuple[str, str, str]
) -> None:
    initiator, responder, responder_clone_id = pair
    _set_cost_split_profile(
        responder_clone_id,
        policy={
            "max_auto_accept_amount": 5000.0,
            "max_negotiable_amount": 30000.0,
            "reservation_ratio": 0.1,
            "concession_ratio": 0.5,
        },
    )
    put_response = client.put(
        "/v1/policies/approval-rules",
        json={"user_id": responder, "rules": {"high_value": False}},
        headers=auth_headers,
    )
    assert put_response.status_code == 200

    # total=100000 -> reservation=10000, offer=35000 (> reservation, > max_negotiable)
    negotiation = _cost_split(
        client,
        auth_headers,
        initiator,
        responder,
        total_amount=100000.0,
        proposed_share=35000.0,
    )
    assert negotiation["status"] == "failed"
    assert negotiation["result"]["code"] == "COST_SHARE_EXCEEDS_LIMIT"

    messages = client.get(
        f"/v1/negotiations/{negotiation['id']}/messages", headers=auth_headers
    ).json()
    assert messages[-1]["message_type"] == "REJECT"
    assert messages[-1]["payload"]["public_reason"] in {
        "constraint_violation",
        "policy_declined",
    }


def _assert_no_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            assert key not in _FORBIDDEN_KEYS, f"forbidden key leaked: {key}"
            _assert_no_forbidden_keys(nested)
    elif isinstance(value, list):
        for item in value:
            _assert_no_forbidden_keys(item)


def test_minimal_information_principle_no_policy_leaks_in_messages(
    client: TestClient, auth_headers: dict[str, str], pair: tuple[str, str, str]
) -> None:
    initiator, responder, responder_clone_id = pair
    _set_cost_split_profile(
        responder_clone_id,
        policy={
            "max_auto_accept_amount": 1000.0,
            "max_negotiable_amount": 30000.0,
            "reservation_ratio": 0.5,
            "concession_ratio": 0.5,
        },
        preference={"preferred_ratio": 0.2},
    )
    negotiation = _cost_split(
        client,
        auth_headers,
        initiator,
        responder,
        total_amount=10000.0,
        proposed_share=3000.0,
    )
    messages = client.get(
        f"/v1/negotiations/{negotiation['id']}/messages", headers=auth_headers
    ).json()
    assert len(messages) >= 1
    for message in messages:
        _assert_no_forbidden_keys(message["payload"])
        _assert_no_forbidden_keys(message["delta"])


def test_escalated_approval_approved_creates_agreement_with_agreed_share(
    client: TestClient, auth_headers: dict[str, str], pair: tuple[str, str, str]
) -> None:
    initiator, responder, _responder_clone_id = pair
    negotiation = _cost_split(
        client,
        auth_headers,
        initiator,
        responder,
        total_amount=10000.0,
        proposed_share=6000.0,
    )
    assert negotiation["status"] == "waiting_approval"
    approval_id = negotiation["pending_approval_id"]
    assert approval_id is not None

    approved = client.post(f"/v1/approvals/{approval_id}/approve", headers=auth_headers)
    assert approved.status_code == 200

    refreshed = client.get(f"/v1/negotiations/{negotiation['id']}", headers=auth_headers).json()
    assert refreshed["status"] == "agreed"

    agreements = client.get("/v1/agreements", headers=auth_headers).json()
    matching = [a for a in agreements if a["session_id"] == negotiation["id"]]
    assert len(matching) == 1
    assert matching[0]["agreed_payload"]["agreed_share"] == 6000.0
    assert matching[0]["agreed_payload"]["intent"] == "cost.split"


# ---------------------------------------------------------------------------
# Phase D: 双方向の効用ベース譲歩（次の一手を決める戦略が純粋関数 next_action に切り出され、
# initiator/responder 双方が交互に COUNTER を出せるようになったことを検証する。
# ---------------------------------------------------------------------------


def _setup_pair_with_clone_ids(
    client: TestClient, auth_headers: dict[str, str]
) -> tuple[str, str, str, str]:
    """initiator_user_id, initiator_clone_id, responder_user_id, responder_clone_id を返す。

    双方向譲歩のテストは initiator 側のポリシーも制御する必要があるため、
    `pair` フィクスチャ（responder のクローンIDしか返さない）を使わずここで独自に組み立てる。
    """
    initiator, responder, responder_clone_id = _setup_pair(client, auth_headers)
    initiator_clones_response = client.get(f"/v1/clones/{initiator}", headers=auth_headers)
    assert initiator_clones_response.status_code == 200
    initiator_clones = initiator_clones_response.json()
    assert len(initiator_clones) == 1
    initiator_clone_id = str(initiator_clones[0]["id"])
    return initiator, initiator_clone_id, responder, responder_clone_id


def _slow_convergence_negotiation(
    client: TestClient, auth_headers: dict[str, str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """3ラウンドでは交差しない、双方が譲歩し合う交渉トレースを1本作る。

    responder: reservation_ratio=0.7 (U=7000), preferred_ratio=0.1 (open_r=1000), concession=0.3
    initiator: reservation_ratio=0.5 (L_policy=5000 -> L=min(5000, 6000)=5000), concession=0.3
    -> round1(responder) counter 2500, round2(initiator) counter 5000,
       round3(responder) は交差せず本来なら counter(3250) だが D3 によりエスカレーションする。
    """
    initiator, initiator_clone_id, responder, responder_clone_id = _setup_pair_with_clone_ids(
        client, auth_headers
    )
    _set_cost_split_profile(
        responder_clone_id,
        policy={
            "max_auto_accept_amount": 100.0,
            "max_negotiable_amount": 50000.0,
            "reservation_ratio": 0.7,
            "concession_ratio": 0.3,
        },
        preference={"preferred_ratio": 0.1},
    )
    _set_cost_split_profile(
        initiator_clone_id,
        policy={
            "max_auto_accept_amount": 100.0,
            "max_negotiable_amount": 50000.0,
            "reservation_ratio": 0.5,
            "concession_ratio": 0.3,
        },
    )
    negotiation = _cost_split(
        client,
        auth_headers,
        initiator,
        responder,
        total_amount=10000.0,
        proposed_share=6000.0,
    )
    messages = client.get(
        f"/v1/negotiations/{negotiation['id']}/messages", headers=auth_headers
    ).json()
    return negotiation, messages


def test_bilateral_concession_both_sides_counter(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """1. 双方向譲歩: initiator と responder の両方が COUNTER を出す。"""
    _negotiation, messages = _slow_convergence_negotiation(client, auth_headers)
    counters = [m for m in messages if m["message_type"] == "COUNTER"]
    assert len(counters) >= 2
    senders = [m["sender_agent_id"] for m in counters]
    # 連続する COUNTER の送信者が交互になっている（片側だけが動き続けていない）。
    assert all(senders[i] != senders[i + 1] for i in range(len(senders) - 1))


def test_monotonicity_responder_nondecreasing_initiator_nonincreasing(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """2. 単調性: responder の提示額は非減少、initiator の要求額は非増加。"""
    _negotiation, messages = _slow_convergence_negotiation(client, auth_headers)
    counters = [m for m in messages if m["message_type"] == "COUNTER"]
    responder_amounts = []
    initiator_amounts = []
    # sender が responder（REQUEST の受信者）かどうかは messages[0] の受信者と比較して判定する。
    request_receiver = messages[0]["receiver_agent_id"]
    for message in counters:
        amount = message["delta"]["proposed_share"]
        if message["sender_agent_id"] == request_receiver:
            responder_amounts.append(amount)
        else:
            initiator_amounts.append(amount)
    assert responder_amounts == sorted(responder_amounts)
    assert initiator_amounts == sorted(initiator_amounts, reverse=True)
    assert len(responder_amounts) >= 1
    assert len(initiator_amounts) >= 1


def test_reservation_price_never_violated(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """3. 留保価格の不可侵: responder の提示は U を超えず、initiator の要求は L を下回らない。"""
    negotiation, messages = _slow_convergence_negotiation(client, auth_headers)
    # このシナリオの U=7000, L=5000（_slow_convergence_negotiation のdocstring参照）。
    reservation_u = 10000.0 * 0.7
    floor_l = 5000.0
    request_receiver = messages[0]["receiver_agent_id"]
    for message in messages:
        if message["message_type"] != "COUNTER":
            continue
        amount = message["delta"]["proposed_share"]
        if message["sender_agent_id"] == request_receiver:
            assert amount <= reservation_u
        else:
            assert amount >= floor_l
    assert negotiation["status"] == "waiting_approval"


def test_zopa_exists_converges_to_agreement_when_concession_ratio_is_one(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """4. ZOPA あり → 合意: concession_ratio を両者1.0にすれば1往復で交差してAGREEDになる。"""
    initiator, initiator_clone_id, responder, responder_clone_id = _setup_pair_with_clone_ids(
        client, auth_headers
    )
    _set_cost_split_profile(
        responder_clone_id,
        policy={
            "max_auto_accept_amount": 100.0,
            "max_negotiable_amount": 50000.0,
            "reservation_ratio": 0.5,
            "concession_ratio": 1.0,
        },
        preference={"preferred_ratio": 0.1},
    )
    _set_cost_split_profile(
        initiator_clone_id,
        policy={
            "max_auto_accept_amount": 100.0,
            "max_negotiable_amount": 50000.0,
            "reservation_ratio": 0.5,
            "concession_ratio": 1.0,
        },
    )
    negotiation = _cost_split(
        client,
        auth_headers,
        initiator,
        responder,
        total_amount=10000.0,
        proposed_share=3000.0,
    )
    assert negotiation["status"] == "agreed"
    assert negotiation["result"]["agreed_share"] == 3000.0
    assert negotiation["result"]["rounds"] == 2

    messages = client.get(
        f"/v1/negotiations/{negotiation['id']}/messages", headers=auth_headers
    ).json()
    assert [m["message_type"] for m in messages] == ["REQUEST", "COUNTER", "ACCEPT"]
    # 交差前に COUNTER (responder) → 交差後に ACCEPT (initiator) と、往復してから合意している。
    assert messages[1]["sender_agent_id"] != messages[2]["sender_agent_id"]


def test_no_zopa_never_agrees(client: TestClient, auth_headers: dict[str, str]) -> None:
    """5. ZOPA なし → 合意しない: L > U になるポリシーで AGREED にならない。"""
    initiator, initiator_clone_id, responder, responder_clone_id = _setup_pair_with_clone_ids(
        client, auth_headers
    )
    _set_cost_split_profile(
        responder_clone_id,
        policy={
            "max_auto_accept_amount": 100.0,
            "max_negotiable_amount": 50000.0,
            "reservation_ratio": 0.3,  # U = 3000
            "concession_ratio": 0.5,
        },
    )
    _set_cost_split_profile(
        initiator_clone_id,
        policy={
            "max_auto_accept_amount": 100.0,
            "max_negotiable_amount": 50000.0,
            "reservation_ratio": 0.5,  # L_policy = 5000
            "concession_ratio": 0.5,
        },
    )
    negotiation = _cost_split(
        client,
        auth_headers,
        initiator,
        responder,
        total_amount=10000.0,
        proposed_share=8000.0,  # L = min(5000, 8000) = 5000 > U = 3000
    )
    assert negotiation["status"] != "agreed"
    assert negotiation["status"] in {"waiting_approval", "failed"}


def test_round_limit_escalates_to_approval_instead_of_auto_accept(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """6. ラウンド上限: ZOPAはあるが concession_ratio が小さく3ラウンドで交差しない設定
    → waiting_approval になり pending_approval_id が立つ（D3の意図的な仕様変更）。
    """
    negotiation, _messages = _slow_convergence_negotiation(client, auth_headers)
    assert negotiation["status"] == "waiting_approval"
    assert negotiation["pending_approval_id"] is not None


def test_minimal_information_principle_bilateral_no_leaks(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """7. 最小情報（拡張）: 双方向譲歩でも policy パラメータがメッセージに漏れない。"""
    _negotiation, messages = _slow_convergence_negotiation(client, auth_headers)
    assert len(messages) >= 3
    for message in messages:
        _assert_no_forbidden_keys(message["payload"])
        _assert_no_forbidden_keys(message["delta"])


def test_next_action_is_a_pure_function_callable_without_session() -> None:
    """8. 戦略の純粋性: next_action は Session を渡さずに直接呼べる。"""
    from enishi_core.domains.cost_split_strategy import OfferState, next_action
    from enishi_core.models import CloneAgent

    responder_clone = CloneAgent(
        policy_profile={
            "cost_split": {
                "max_auto_accept_amount": 100.0,
                "max_negotiable_amount": 50000.0,
                "reservation_ratio": 0.7,
                "concession_ratio": 0.3,
            }
        },
        preference_profile={"cost_split": {"preferred_ratio": 0.1}},
    )

    action = next_action(
        clone=responder_clone,
        role="responder",
        total_amount=10000.0,
        proposed_share=6000.0,
        state=OfferState(round_number=1, standing_offer=6000.0, my_last_offer=None),
    )

    assert action.kind == "counter"
    assert action.amount == 2500.0
    assert action.reason_codes == []

    initiator_clone = CloneAgent(
        policy_profile={
            "cost_split": {
                "reservation_ratio": 0.5,
                "concession_ratio": 0.3,
            }
        },
    )
    accept_action = next_action(
        clone=initiator_clone,
        role="initiator",
        total_amount=10000.0,
        proposed_share=3000.0,
        state=OfferState(round_number=2, standing_offer=3000.0, my_last_offer=3000.0),
    )
    assert accept_action.kind == "accept"
    assert accept_action.amount == 3000.0


# ---------------------------------------------------------------------------
# Phase E: E1（initiator の下限到達は escalate、reject ではない）/ E2（decider_clone_id の
# de-hardcode、responder決め打ちからの脱却）を検証する。
# ---------------------------------------------------------------------------


def test_initiator_action_escalates_when_conceded_to_floor_but_offer_still_below() -> None:
    """新規1. E1（戦略）: initiator が既に下限Lまで譲歩済みで、相手の提示がまだLに届かない場合、
    reject ではなく escalate(["cost_share_below_reservation"]) を返す（純粋関数、Session不要）。
    """
    from enishi_core.domains.cost_split_strategy import OfferState, _initiator_action
    from enishi_core.models import CloneAgent

    initiator_clone = CloneAgent(
        policy_profile={
            "cost_split": {
                "reservation_ratio": 0.5,
                "concession_ratio": 0.5,
            }
        },
    )
    # total=10000 -> L_policy=5000, proposed_share=3000 -> floor=min(5000,3000)=3000
    # 既に floor まで譲歩済み(my_last_offer=3000)、相手の提示(2000)はまだ floor に届かない
    action = _initiator_action(
        initiator_clone,
        total_amount=10000.0,
        proposed_share=3000.0,
        state=OfferState(round_number=3, standing_offer=2000.0, my_last_offer=3000.0),
    )
    assert action.kind == "escalate"
    assert action.amount is None
    assert action.reason_codes == ["cost_share_below_reservation"]


def test_initiator_escalation_creates_approval_for_initiators_owner(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """新規2. E1（ドライバ）: initiator が譲歩の下限に達しても responder の提示が届かない場合、
    reject ではなく escalate し、approval は responder ではなく initiator の所有者へ作られる。
    """
    initiator, initiator_clone_id, responder, responder_clone_id = _setup_pair_with_clone_ids(
        client, auth_headers
    )
    _set_cost_split_profile(
        initiator_clone_id,
        policy={
            "max_auto_accept_amount": 100.0,
            "max_negotiable_amount": 50000.0,
            "reservation_ratio": 0.5,
            "concession_ratio": 0.5,
        },
    )
    _set_cost_split_profile(
        responder_clone_id,
        policy={
            "max_auto_accept_amount": 100.0,
            "max_negotiable_amount": 50000.0,
            "reservation_ratio": 0.6,
            "concession_ratio": 0.5,
        },
        preference={"preferred_ratio": 0.1},
    )
    # total=10000, proposed_share=3000 -> floor=min(5000,3000)=3000
    # （initiatorの要求は既に自分の下限）
    # round1(responder): opening=1000, counter -> min(6000,1000+(3000-1000)*0.5)=2000
    # round2(initiator): x_i=3000<=floor(3000) かつ standing=2000<floor(3000) -> escalate
    negotiation = _cost_split(
        client,
        auth_headers,
        initiator,
        responder,
        total_amount=10000.0,
        proposed_share=3000.0,
    )
    assert negotiation["status"] == "waiting_approval"
    approval_id = negotiation["pending_approval_id"]
    assert approval_id is not None

    approvals = client.get(f"/v1/approvals?user_id={initiator}", headers=auth_headers).json()
    matching = [a for a in approvals if a["id"] == approval_id]
    assert len(matching) == 1, "approval は initiator の所有者へ作られるべき"
    approval = matching[0]
    assert approval["user_id"] == initiator
    assert approval["payload"]["decider_clone_id"] == initiator_clone_id
    assert approval["payload"]["reason"] == "cost_share_below_reservation"

    # responder 側には作られない
    responder_approvals = client.get(
        f"/v1/approvals?user_id={responder}", headers=auth_headers
    ).json()
    assert all(a["id"] != approval_id for a in responder_approvals)


def test_max_rounds_parity_independent_initiator_can_be_final_decider(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """新規3. E1+E2: `_MAX_ROUNDS` を偶数(4)に monkeypatch しても、最終手番が initiator に
    なった場合に initiator の所有者へ正しくエスカレーションされ、承認解決時も initiator が
    送信者になる（responder 決め打ち・奇数ラウンド決め打ちのどちらにも依存しないことの証明）。
    """
    import enishi_core.domains.cost_split as cost_split_module

    monkeypatch.setattr(cost_split_module, "_MAX_ROUNDS", 4)

    negotiation, messages = _slow_convergence_negotiation(client, auth_headers)
    assert negotiation["status"] == "waiting_approval"
    approval_id = negotiation["pending_approval_id"]
    assert approval_id is not None

    initiator_clone_id = messages[0]["sender_agent_id"]
    responder_clone_id = messages[0]["receiver_agent_id"]

    approvals = client.get("/v1/approvals", headers=auth_headers).json()
    approval = next(a for a in approvals if a["id"] == approval_id)
    # ラウンド4（偶数）の手番は initiator 側であり、decider は initiator。
    assert approval["payload"]["decider_clone_id"] == initiator_clone_id
    assert approval["payload"]["reason"] == "cost_share_below_reservation"

    approved = client.post(f"/v1/approvals/{approval_id}/approve", headers=auth_headers)
    assert approved.status_code == 200

    resolved_messages = client.get(
        f"/v1/negotiations/{negotiation['id']}/messages", headers=auth_headers
    ).json()
    final = resolved_messages[-1]
    assert final["message_type"] == "ACCEPT"
    # E2: responder 決め打ちなら sender は responder_clone_id になってしまうが、
    # decider_clone_id を参照するため initiator が送信者になる。
    assert final["sender_agent_id"] == initiator_clone_id
    assert final["receiver_agent_id"] == responder_clone_id


def test_on_approval_resolved_falls_back_to_responder_without_decider_clone_id(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """新規4. E2: payload に decider_clone_id が無い approval（E2以前・他ドメイン由来を模す）は
    従来どおり responder が送信者になる（後方互換フォールバック）。
    """
    from enishi_core.database import get_session
    from enishi_core.models import (
        Approval,
        ApprovalStatus,
        NegotiationMessage,
        NegotiationSession,
        NegotiationStatus,
    )
    from enishi_core.services import approvals as approval_service
    from enishi_core.services.negotiation import on_approval_resolved

    _initiator, initiator_clone_id, responder, responder_clone_id = _setup_pair_with_clone_ids(
        client, auth_headers
    )
    session = next(get_session())
    try:
        negotiation = NegotiationSession(
            initiator_clone_id=initiator_clone_id,
            responder_clone_id=responder_clone_id,
            intent="cost.split",
            topic="旧形式承認",
            status=NegotiationStatus.WAITING_APPROVAL.value,
        )
        session.add(negotiation)
        session.flush()
        approval: Approval = approval_service.create_approval(
            session,
            user_id=responder,
            action_type="negotiation_decision",
            description="テスト",
            level=1,
            payload={
                "session_id": negotiation.id,
                "intent": "cost.split",
                "reason": "cost_share_exceeds_reservation",
                "proposed_action": "ACCEPT",
                "payload": {"agreed_share": 4000.0},
                # decider_clone_id をあえて積まない（E2以前に作られた approval を模す）
            },
        )
        negotiation.pending_approval_id = approval.id
        session.commit()

        approval.status = ApprovalStatus.APPROVED.value
        on_approval_resolved(session, approval)

        message = (
            session.query(NegotiationMessage)
            .filter_by(session_id=negotiation.id)
            .order_by(NegotiationMessage.sequence.desc())
            .first()
        )
        assert message is not None
        assert message.sender_agent_id == responder_clone_id
        assert message.receiver_agent_id == initiator_clone_id
    finally:
        session.close()
