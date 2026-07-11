from fastapi.testclient import TestClient


def test_create_and_list_users(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = client.post(
        "/v1/users",
        json={"display_name": "中村"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["display_name"] == "中村"
    assert body["timezone"] == "Asia/Tokyo"
    assert body["language"] == "ja"

    listed = client.get("/v1/users", headers=auth_headers)
    assert listed.status_code == 200
    assert [u["id"] for u in listed.json()] == [body["id"]]


def test_create_user_rejects_empty_name(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post("/v1/users", json={"display_name": ""}, headers=auth_headers)
    assert response.status_code == 422
