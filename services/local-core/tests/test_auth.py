import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def test_v1_requires_token(client: TestClient) -> None:
    response = client.get("/v1/users")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "LOCAL_CORE_UNAUTHORIZED"


def test_v1_rejects_wrong_token(client: TestClient) -> None:
    response = client.get("/v1/users", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_v1_rejects_non_ascii_authorization_with_401(client: TestClient) -> None:
    # サーバーはヘッダーをlatin-1で復号するため非ASCIIのstrになる。
    # str同士の secrets.compare_digest は TypeError（HTTP 500）になるので、401でなければならない。
    response = client.get(
        "/v1/users", headers={"Authorization": "Bearer トークン-é".encode()}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "LOCAL_CORE_UNAUTHORIZED"


def test_websocket_rejects_non_ascii_authorization(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(
            "/v1/tasks/missing/stream",
            headers={"Authorization": "Bearer é".encode()},
        ) as websocket:
            websocket.receive_text()
    # ルーター依存の認証がハンドシェイク段階で拒否する（HTTP 401）。500であってはならない。
    assert getattr(excinfo.value, "status_code", None) == 401


def test_presentation_ui_origin_is_allowed(client: TestClient) -> None:
    response = client.options(
        "/v1/approvals",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_tauri_app_origin_is_allowed(client: TestClient) -> None:
    response = client.options(
        "/v1/approvals",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


def test_untrusted_browser_origin_is_not_allowed(client: TestClient) -> None:
    response = client.options(
        "/v1/approvals",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_v1_accepts_valid_token(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/v1/users", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []
