"""Phase F3: 名刺の能力宣言（.tmp/phase-f2-f4-spec.md 新規テスト4）。

`supported_intents` は `domains.registered_intents()` から動的に生成され、
`supports_remote=True` のドメインだけが含まれることを確認する。
"""

from enishi_core.database import get_session
from enishi_core.services.identity_cards import create_card
from fastapi.testclient import TestClient


def test_card_supported_intents_only_includes_supports_remote_domains(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post("/v1/users", json={"display_name": "中村"}, headers=auth_headers)
    assert response.status_code == 201
    user_id = str(response.json()["id"])

    session = next(get_session())
    try:
        card = create_card(session, user_id)
    finally:
        session.close()

    supported_intents = card["capabilities"]["supported_intents"]
    assert supported_intents == ["meeting.schedule"]
    # supports_remote=False のドメインは宣言しない（実装していない能力を約束しないため）。
    assert "task.request" not in supported_intents
    assert "cost.split" not in supported_intents
