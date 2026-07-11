from fastapi.testclient import TestClient


def test_v1_requires_token(client: TestClient) -> None:
    response = client.get("/v1/users")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "LOCAL_CORE_UNAUTHORIZED"


def test_v1_rejects_wrong_token(client: TestClient) -> None:
    response = client.get("/v1/users", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_v1_accepts_valid_token(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/v1/users", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []
