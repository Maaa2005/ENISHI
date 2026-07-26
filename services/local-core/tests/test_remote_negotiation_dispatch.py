"""Phase F4: エラーの2分割と、交渉開始時の intent dispatch
（.tmp/phase-f2-f4-spec.md 新規テスト5〜7）。
"""

from typing import Any

import pytest
from enishi_core.services.intent_interpreter import InterpretedRequest
from fastapi.testclient import TestClient

_PUBLIC_KEY = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="


class _FakeRelay:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(self, envelope: dict[str, Any]) -> None:
        self.sent.append(envelope)

    def fetch(self) -> list[dict[str, Any]]:
        return []

    def ack(self, delivery_id: str) -> None:
        pass


class _StubInterpreter:
    """任意のintent/payloadを固定で返す解釈層のスタブ（LLM/正規表現をバイパスする）。"""

    def __init__(self, result: InterpretedRequest) -> None:
        self._result = result

    def interpret(self, text: str) -> InterpretedRequest:
        return self._result


def _user(client: TestClient, headers: dict[str, str], name: str = "中村") -> str:
    response = client.post("/v1/users", json={"display_name": name}, headers=headers)
    assert response.status_code == 201
    return str(response.json()["id"])


def _activate(client: TestClient, headers: dict[str, str], user_id: str) -> None:
    clone = client.post(
        f"/v1/clones/{user_id}/ensure",
        json={"purpose": "交渉", "provider_type": "mock"},
        headers=headers,
    ).json()
    assert client.post(f"/v1/clones/{clone['id']}/activate", headers=headers).status_code == 200


def _trusted_peer(
    client: TestClient, headers: dict[str, str], agent_id: str = "agt_peer_node"
) -> None:
    created = client.post(
        "/v1/peers",
        json={
            "agent_id": agent_id,
            "display_name": "相手AI",
            "public_key": _PUBLIC_KEY,
        },
        headers=headers,
    )
    assert created.status_code == 201
    assert client.post(f"/v1/peers/{agent_id}/trust", headers=headers).status_code == 200


def test_cost_split_remote_request_to_v1_peer_returns_409_capability_mismatch(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """新規テスト5（F5完了後の書き直し）: `cost.split` を自然言語経由で遠隔依頼すると、
    `CostSplitDomain.supports_remote` が `True` になった今、422
    `INTENT_NOT_SUPPORTED_FOR_REMOTE_REQUEST` はもう返らない。代わりに、能力宣言のない
    v1ピア（本テストの `_trusted_peer` は capabilities なしで登録する）は meeting.schedule
    以外の遠隔交渉を許可しないため、既存の409 `PEER_CAPABILITY_MISMATCH` に到達する
    （「相手が cost.split に対応していない」という正しい理由）。

    NOTE(F5前の履歴): このテストはF5完了前は
    `test_cost_split_remote_request_returns_422_enishi_not_implemented` という名前で、
    ENISHI自身が未実装であることを理由に422を返すことを検証していた。
    """
    relay = _FakeRelay()
    monkeypatch.setattr("enishi_core.api.routes.get_relay_client", lambda: relay)
    monkeypatch.setattr(
        "enishi_core.services.agent_requests.get_interpreter",
        lambda *args, **kwargs: _StubInterpreter(
            InterpretedRequest(
                intent="cost.split",
                payload={
                    "title": "飲み会の割り勘",
                    "total_amount": 10000.0,
                    "currency": "JPY",
                    "proposed_share": 3000.0,
                },
            )
        ),
    )
    user_id = _user(client, auth_headers)
    _activate(client, auth_headers, user_id)
    _trusted_peer(client, auth_headers)

    response = client.post(
        "/v1/agent/requests",
        json={"user_id": user_id, "text": "飲み会の割り勘をお願い"},
        headers=auth_headers,
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "PEER_CAPABILITY_MISMATCH"
    assert body["error"]["details"]["intent"] == "cost.split"
    assert relay.sent == []


def test_remote_negotiation_create_legacy_flat_format_starts_same_negotiation(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """新規テスト6: `RemoteNegotiationCreate` の旧フラット形式（topic/duration_minutes/...を
    トップレベルに直接持つ形）が `payload` へ畳み込まれ、従来と同じ遠隔交渉が開始される
    （Phase B の `NegotiationCreate` と同じ後方互換パターンの証明）。
    """
    relay = _FakeRelay()
    monkeypatch.setattr("enishi_core.api.routes.get_relay_client", lambda: relay)
    user_id = _user(client, auth_headers)
    _activate(client, auth_headers, user_id)
    _trusted_peer(client, auth_headers)

    response = client.post(
        "/v1/remote-negotiations",
        json={
            "user_id": user_id,
            "peer_agent_id": "agt_peer_node",
            "topic": "旧形式での遠隔交渉",
            "duration_minutes": 30,
            "date_range": {"start": "2026-08-10", "end": "2026-08-10"},
            "preferred_time_ranges": [{"start": "10:00", "end": "12:00"}],
        },
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["intent"] == "meeting.schedule"
    assert body["topic"] == "旧形式での遠隔交渉"
    assert len(relay.sent) == 2
    assert relay.sent[0]["message_type"] == "REQUEST"
    assert relay.sent[0]["payload"]["topic"] == "旧形式での遠隔交渉"
    assert relay.sent[0]["payload"]["duration_minutes"] == 30
    assert relay.sent[1]["message_type"] == "PROPOSE"


def test_remote_negotiation_create_unknown_intent_returns_422(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """新規テスト7: `RemoteNegotiationCreate` に未登録 intent を渡すと422になる。"""
    user_id = _user(client, auth_headers)
    _activate(client, auth_headers, user_id)
    _trusted_peer(client, auth_headers)

    response = client.post(
        "/v1/remote-negotiations",
        json={
            "user_id": user_id,
            "peer_agent_id": "agt_peer_node",
            "intent": "expense.approval",
            "payload": {},
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "UNKNOWN_INTENT"


def test_remote_negotiation_malformed_payload_rejected_before_relay(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`payload` が不透明なdictになったことで失われたスキーマ層の検証を、ドメイン検証で埋める。

    相手ノードへ送る経路なので、不正入力がワイヤに載ってはいけない。422で拒否され、
    かつ Relay へ1通も送信されていないことを確認する。
    """
    relay = _FakeRelay()
    monkeypatch.setattr("enishi_core.api.routes.get_relay_client", lambda: relay)
    user_id = _user(client, auth_headers)
    _activate(client, auth_headers, user_id)
    _trusted_peer(client, auth_headers)

    response = client.post(
        "/v1/remote-negotiations",
        json={
            "user_id": user_id,
            "peer_agent_id": "agt_peer_node",
            "intent": "meeting.schedule",
            # date_range と preferred_time_ranges が欠けており、duration_minutes も上限超過。
            "payload": {"topic": "壊れた依頼", "duration_minutes": 100000},
        },
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert relay.sent == []
