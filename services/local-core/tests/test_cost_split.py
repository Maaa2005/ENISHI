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
